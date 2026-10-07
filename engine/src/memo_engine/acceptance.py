from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable

from docx import Document

from .canonical import _iter_blocks, build_canonical_memo, validate_canonical
from .corrections import apply_confirmed_corrections, attach_correction_audit
from .ingestion import ingest_bytes, validate_source_path
from .normalization import normalize_source
from .phase7_5 import enrich_structure_phase7_5
from .renderer import render_outputs
from .semantic import build_semantic_plan, interpret_semantics
from .structure import extract_structure


BUCKET = "memo-files"
EXPECTED_PROJECT_REF = "njrqiurqljwtuqrvguhj"
GEOMETRY_CATEGORY = "geometry_line_relationship_conflict"
GEOMETRY_AFFECTED_ID = "3.2"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AcceptanceFailure(RuntimeError):
    """A sanitized acceptance failure safe for a public workflow log."""


class ReadOnlySupabase:
    """Minimum private-read client for hosted acceptance.

    This class intentionally has no upload, patch, event, exception, or
    correction mutation methods. All network traffic passes through the GET-only
    guard below.
    """

    def __init__(self, base: str | None = None, secret: str | None = None) -> None:
        self.base = (base or os.environ["SUPABASE_URL"]).rstrip("/")
        self.__secret = secret or os.environ["SUPABASE_SECRET_KEY"]
        host = urllib.parse.urlparse(self.base).hostname or ""
        if host != f"{EXPECTED_PROJECT_REF}.supabase.co":
            raise AcceptanceFailure("ACCEPTANCE_PROJECT_REF_MISMATCH")

    def _request_bytes(self, method: str, path: str) -> bytes:
        method = method.upper()
        if method != "GET":
            raise AcceptanceFailure(f"READ_ONLY_HTTP_METHOD_REJECTED:{method}")
        request = urllib.request.Request(
            f"{self.base}{path}",
            method="GET",
            headers={"apikey": self.__secret},
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise AcceptanceFailure(
                f"READ_ONLY_SUPABASE_HTTP_ERROR:{exc.code}"
            ) from exc

    def _get_json(self, path: str) -> Any:
        raw = self._request_bytes("GET", path)
        return json.loads(raw.decode("utf-8")) if raw else None

    def get_job(self, job_id: str) -> dict[str, Any]:
        job_q = urllib.parse.quote(job_id, safe="")
        rows = self._get_json(f"/rest/v1/jobs?id=eq.{job_q}&select=*")
        if not isinstance(rows, list) or len(rows) != 1:
            raise AcceptanceFailure("SOURCE_JOB_NOT_FOUND_OR_NOT_UNIQUE")
        return rows[0]

    def download_object(self, bucket: str, object_path: str) -> bytes:
        bucket_q = urllib.parse.quote(bucket, safe="")
        path_q = urllib.parse.quote(object_path, safe="/")
        return self._request_bytes(
            "GET", f"/storage/v1/object/{bucket_q}/{path_q}"
        )

    def download_json(self, bucket: str, object_path: str) -> Any:
        return json.loads(self.download_object(bucket, object_path).decode("utf-8"))

    def get_confirmed_corrections(self, job_id: str) -> list[dict[str, Any]]:
        job_q = urllib.parse.quote(job_id, safe="")
        rows = self._get_json(
            "/rest/v1/corrections"
            f"?job_id=eq.{job_q}"
            "&confirmation_status=eq.confirmed"
            "&select=id,job_id,user_id,exception_id,input_kind,typed_text,storage_path,display_text,proposed_patch,confirmation_status,created_at,confirmed_at,applied_at,updated_at"
            "&order=confirmed_at.asc,id.asc"
        )
        return rows if isinstance(rows, list) else []

    def get_correction_state(self, job_id: str) -> list[dict[str, Any]]:
        job_q = urllib.parse.quote(job_id, safe="")
        rows = self._get_json(
            "/rest/v1/corrections"
            f"?job_id=eq.{job_q}"
            "&select=id,confirmation_status,confirmed_at,applied_at,updated_at"
            "&order=id.asc"
        )
        return rows if isinstance(rows, list) else []

    def get_event_state(self, job_id: str) -> list[dict[str, Any]]:
        job_q = urllib.parse.quote(job_id, safe="")
        rows = self._get_json(
            "/rest/v1/job_events"
            f"?job_id=eq.{job_q}"
            "&select=id,event_type,stage,created_at"
            "&order=id.asc"
        )
        return rows if isinstance(rows, list) else []


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceFailure(code)


def _semantic_signature(structure: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    deterministic, candidates = build_semantic_plan(structure)
    result: dict[str, tuple[Any, ...]] = {}
    for item in deterministic + candidates:
        result[str(item.get("candidate_id"))] = (
            str(item.get("question_id")),
            int(item.get("mark_index") or 0),
            int(item.get("count") or 0),
            item.get("source_shorthand"),
            str(item.get("descriptor") or ""),
            item.get("source_notation"),
            item.get("source_semantic"),
            str(item.get("question_context") or ""),
            json.dumps(item.get("neighboring_marks") or [], sort_keys=True),
            item.get("resolution_method") == "deterministic",
        )
    return result


def _cached_semantic_matches(
    structure: dict[str, Any], cached: dict[str, Any]
) -> bool:
    if cached.get("phase") != "phase4_semantics":
        return False
    observed: dict[str, tuple[Any, ...]] = {}
    try:
        for item in cached.get("deterministic_results", []) + cached.get("ai_results", []):
            observed[str(item["candidate_id"])] = (
                str(item["question_id"]),
                int(item["mark_index"]),
                int(item.get("count") or 0),
                item.get("source_shorthand"),
                str(item.get("descriptor") or ""),
                item.get("source_notation"),
                item.get("source_semantic"),
                str(item.get("question_context") or ""),
                json.dumps(item.get("neighboring_marks") or [], sort_keys=True),
                item.get("resolution_method") == "deterministic",
            )
    except (KeyError, TypeError, ValueError):
        return False
    expected = _semantic_signature(structure)
    return bool(expected) and expected == observed


def _semantics_for_replay(
    structure: dict[str, Any], cached: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    if isinstance(cached, dict) and _cached_semantic_matches(structure, cached):
        semantic = copy.deepcopy(cached)
        semantic["interpreter_runs"] = []
        summary = dict(semantic.get("summary") or {})
        summary["interpreter_run_count"] = 0
        summary["ai_cache_reused_count"] = len(semantic.get("ai_results", []))
        semantic["summary"] = summary
        semantic["cache"] = {"reused": True, "mode": "exact"}
        return semantic, "exact"
    semantic = interpret_semantics(structure)
    semantic["cache"] = {"reused": False, "mode": "none"}
    return semantic, "none"


def _open_exceptions(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in canonical.get("exceptions", [])
        if item.get("status") == "open"
    ]


def _validate_correction_overlay(
    structure: dict[str, Any], expected_confirmed: int
) -> dict[str, int]:
    overlay = structure.get("correction_overlay") or {}
    history = overlay.get("history") or []
    _require(overlay.get("confirmed_count") == expected_confirmed, "CORRECTION_CONFIRMED_COUNT_MISMATCH")
    _require(overlay.get("issue_count") == 0, "CORRECTION_OVERLAY_ISSUE")
    _require(overlay.get("applied_count") == overlay.get("effective_count"), "CORRECTION_EFFECTIVE_NOT_APPLIED")
    _require(
        all(item.get("effective") or item.get("superseded_by") for item in history),
        "CORRECTION_SUPERSESSION_LINK_MISSING",
    )
    return {
        "confirmed_count": int(overlay.get("confirmed_count") or 0),
        "effective_count": int(overlay.get("effective_count") or 0),
        "superseded_count": int(overlay.get("superseded_count") or 0),
        "applied_count": int(overlay.get("applied_count") or 0),
        "application_issue_count": int(overlay.get("issue_count") or 0),
    }


def _find_item(canonical: dict[str, Any], number: str) -> dict[str, Any] | None:
    def visit(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        for item in items:
            if str(item.get("number")) == number:
                return item
            match = visit(item.get("children", []))
            if match is not None:
                return match
        return None

    for question in canonical.get("questions", []):
        match = visit(question.get("items", []))
        if match is not None:
            return match
    return None


def _figure_ownership(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []

    def add(owner: str, blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            if block.get("type") == "figure":
                figures.append({
                    "owner": owner,
                    "asset_id": str((block.get("figure") or {}).get("asset_id")),
                    "media_class": (block.get("figure") or {}).get("media_class"),
                    "source_refs": copy.deepcopy(block.get("source_refs") or []),
                })

    def visit(items: list[dict[str, Any]]) -> None:
        for item in items:
            owner = str(item.get("number"))
            add(owner, item.get("context_blocks", []))
            for alternative in item.get("alternatives", []):
                add(owner, alternative.get("blocks", []))
            visit(item.get("children", []))

    for question in canonical.get("questions", []):
        add("Q" + str(question.get("number")), question.get("context_blocks", []))
        visit(question.get("items", []))
    return figures


def _anchor_key(figure: dict[str, Any]) -> tuple[int, ...]:
    refs = figure.get("source_refs") or []
    anchor = (refs[0].get("docx_anchor") if refs else None) or {}
    return tuple(
        int(anchor.get(key) if anchor.get(key) is not None else -1)
        for key in ("unit_index", "row_index", "cell_index", "paragraph_index", "drawing_order")
    )


def _media_acceptance(
    normalized: dict[str, Any], canonical: dict[str, Any]
) -> dict[str, Any]:
    entities = list((normalized.get("content") or {}).get("media_entities") or [])
    figures = _figure_ownership(canonical)
    asset_map = {
        str(asset.get("asset_id")): asset
        for asset in (canonical.get("source") or {}).get("assets", [])
    }
    substantive = [item for item in figures if item.get("media_class") == "substantive_figure"]
    contextual = [item for item in figures if item.get("media_class") == "contextual_raster"]
    owners = {item["owner"] for item in substantive}
    required_roles = {
        "q1_major_context": "Q1" in owners,
        "q2_association": "2.1" in owners,
        "q3_major_context": "Q3" in owners,
        "q4_major_context": "Q4" in owners,
        "q5_triangle": "Q5" in owners,
        "q61_graph": "6.1" in owners,
        "q9_association": "9.1" in owners,
    }
    q5_context = [item for item in contextual if item["owner"] == "Q5"]
    q61 = [item for item in substantive if item["owner"] == "6.1"]
    q61_item = _find_item(canonical, "6.1")
    q61_asset = asset_map.get(q61[0]["asset_id"], {}) if len(q61) == 1 else {}
    q61_ref = (
        ((q61[0].get("source_refs") or [{}])[0].get("docx_anchor") or {})
        if len(q61) == 1 else {}
    )
    source_anchor = dict(q61_asset.get("source_anchor") or {})
    source_anchor.pop("page", None)

    _require(len(entities) == 10, "MEDIA_NORMALIZED_COUNT_MISMATCH")
    _require(len(figures) == 10, "MEDIA_CANONICAL_COUNT_MISMATCH")
    _require(len({item["asset_id"] for item in figures}) == len(figures), "MEDIA_OWNERSHIP_DUPLICATE")
    _require(len(substantive) == 7, "SUBSTANTIVE_FIGURE_COUNT_MISMATCH")
    _require(all(required_roles.values()), "REQUIRED_FIGURE_ROLE_MISSING")
    _require(len(q5_context) == 2, "Q5_CONTEXTUAL_RASTER_COUNT_MISMATCH")
    _require([_anchor_key(item) for item in q5_context] == sorted(_anchor_key(item) for item in q5_context), "Q5_CONTEXTUAL_RASTER_ORDER_MISMATCH")
    _require(len(q61) == 1, "Q61_GRAPH_OWNERSHIP_MISMATCH")
    _require((q61_item or {}).get("correction_origin", {}).get("source_block_index") is None, "Q61_SOURCE_BLOCK_FABRICATED")
    _require(bool(source_anchor) and q61_ref == source_anchor, "Q61_GRAPH_PROVENANCE_MISMATCH")
    unresolved_ids = {
        str(item.get("asset_id")) for item in entities
        if item.get("media_class") == "unresolved_media"
    }
    _require(unresolved_ids.issubset({item["asset_id"] for item in figures}), "UNRESOLVED_MEDIA_DISCARDED")
    _require({"Q1", "Q3", "Q4"}.issubset({item["owner"] for item in figures}), "AMBIGUOUS_PARENT_MEDIA_GUESSED")

    return {
        "normalized_media_count": len(entities),
        "canonical_media_count": len(figures),
        "substantive_figure_count": len(substantive),
        "contextual_raster_count": len(contextual),
        "required_figure_roles_present": True,
        "media_role_names": sorted(required_roles),
        "q61_identifier_source_block_index": None,
        "q61_graph_original_provenance_preserved": True,
        "duplicate_ownership": False,
        "ambiguous_media_retained_at_parent": True,
    }


def _canonical_block_text(block: dict[str, Any]) -> str:
    if block.get("type") == "math":
        math = block.get("math") or {}
        return str(math.get("plain_text") or math.get("source_text") or "").strip()
    return str(block.get("text") or "").strip()


def _non_target_content_fingerprint(
    canonical: dict[str, Any], excluded_number: str
) -> str:
    content: list[dict[str, Any]] = []

    def visit(items: list[dict[str, Any]]) -> None:
        for item in items:
            number = str(item.get("number"))
            if number != excluded_number:
                content.append({
                    "number": number,
                    "context_blocks": item.get("context_blocks", []),
                    "alternatives": item.get("alternatives", []),
                    "marks": item.get("marks", {}),
                    "source_refs": item.get("source_refs", []),
                })
            visit(item.get("children", []))

    for question in canonical.get("questions", []):
        visit(question.get("items", []))
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ephemeral_geometry_correction(canonical: dict[str, Any]) -> dict[str, Any]:
    item = _find_item(canonical, GEOMETRY_AFFECTED_ID)
    _require(item is not None, "Q32_ITEM_MISSING")
    alternatives = item.get("alternatives", [])
    _require(len(alternatives) == 1, "Q32_ALTERNATIVE_COUNT_UNEXPECTED")
    lines = [
        text for block in alternatives[0].get("blocks", [])
        if (text := _canonical_block_text(block))
    ]
    pattern = re.compile(r"(?i)\bBC\s*(?:is\s+)?(?:perpendicular(?:\s+to)?|⊥)\s*BC\b")
    changed = 0
    corrected: list[str] = []
    for line in lines:
        replacement, count = pattern.subn("BC perpendicular AB", line)
        corrected.append(replacement)
        changed += count
    _require(changed == 1, "Q32_EPHEMERAL_TARGET_NOT_UNIQUE")
    return {
        "id": "phase81a-ephemeral-q32",
        "job_id": canonical.get("audit", {}).get("job_id"),
        "input_kind": "suggestion",
        "display_text": "Ephemeral hosted acceptance geometry correction",
        "confirmation_status": "confirmed",
        "created_at": "9999-12-31T23:59:58+00:00",
        "confirmed_at": "9999-12-31T23:59:59+00:00",
        "applied_at": None,
        "proposed_patch": {
            "operation": "replace_item_content",
            "category": GEOMETRY_CATEGORY,
            "affected_id": GEOMETRY_AFFECTED_ID,
            "target_id": GEOMETRY_AFFECTED_ID,
            "question_text": None,
            "solution_lines": corrected,
        },
    }


def _run_replay(
    job: dict[str, Any],
    source_bytes: bytes,
    corrections: list[dict[str, Any]],
    cached_semantic: dict[str, Any],
) -> dict[str, Any]:
    ingestion = ingest_bytes(job, source_bytes)
    normalized = normalize_source(job, source_bytes, ingestion)
    structure = enrich_structure_phase7_5(extract_structure(normalized), normalized)
    structure, applied, application_issues = apply_confirmed_corrections(
        structure, normalized, corrections
    )
    semantic, cache_mode = _semantics_for_replay(structure, cached_semantic)
    canonical, validation, new_exceptions = build_canonical_memo(
        job, ingestion, normalized, structure, semantic, source_bytes
    )
    attach_correction_audit(canonical, corrections, structure["correction_overlay"])
    validation = validate_canonical(canonical)
    return {
        "ingestion": ingestion,
        "normalized": normalized,
        "structure": structure,
        "semantic": semantic,
        "canonical": canonical,
        "validation": validation,
        "new_exceptions": new_exceptions,
        "applied": applied,
        "application_issues": application_issues,
        "cache_mode": cache_mode,
    }


def _rendered_source_media(
    docx_path: str | Path, canonical: dict[str, Any]
) -> dict[str, int]:
    source_digests = {
        str(asset.get("asset_id")): str(asset.get("sha256"))
        for asset in (canonical.get("source") or {}).get("assets", [])
        if asset.get("sha256")
    }
    counts = {asset_id: 0 for asset_id in source_digests}
    with zipfile.ZipFile(docx_path) as archive:
        rendered = [
            hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith("word/media/") and not name.endswith("/")
        ]
    for asset_id, digest in source_digests.items():
        counts[asset_id] = rendered.count(digest)
    return counts


def _cover_page_count_matches(docx_path: str | Path, page_count: int) -> bool:
    document = Document(str(docx_path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    expected = f"This marking guideline consists of {page_count} pages including the cover page."
    return expected in text


def _snapshot(client: ReadOnlySupabase, job_id: str) -> dict[str, Any]:
    job = client.get_job(job_id)
    corrections = client.get_correction_state(job_id)
    events = client.get_event_state(job_id)
    render_path = f"{job['user_id']}/{job_id}/internal/render_validation.json"
    try:
        render_validation = client.download_json(BUCKET, render_path)
    except AcceptanceFailure:
        render_validation = {}
    return {
        "job": {
            key: job.get(key)
            for key in ("status", "stage", "attempt_count", "updated_at", "review_required")
        },
        "corrections": corrections,
        "events": events,
        "output_hashes": {
            "docx": ((render_validation.get("docx") or {}).get("sha256")),
            "pdf": ((render_validation.get("pdf") or {}).get("sha256")),
        },
    }


def _assert_sanitized_report(report: dict[str, Any]) -> None:
    forbidden_keys = {
        "text", "source_text", "typed_text", "display_text", "proposed_patch",
        "message", "suggestions", "secret", "token", "correction_bodies",
    }
    secret_markers = (
        "sb_secret_", "service_role", "github_token", "groq_api_key",
        "supabase_secret_key",
    )

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            _require(
                not forbidden_keys.intersection(str(key).lower() for key in value),
                "SANITIZED_REPORT_FORBIDDEN_FIELD",
            )
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        elif isinstance(value, str):
            lowered = value.lower()
            _require(
                not any(marker in lowered for marker in secret_markers),
                "SANITIZED_REPORT_SECRET_MARKER",
            )

    inspect(report)


def run_phase81a_acceptance(
    source_job_id: str,
    *,
    client: ReadOnlySupabase | None = None,
    renderer: Callable[[dict[str, Any], bytes, str | Path], dict[str, Any]] = render_outputs,
) -> dict[str, Any]:
    try:
        uuid.UUID(source_job_id)
    except ValueError as exc:
        raise AcceptanceFailure("SOURCE_JOB_ID_INVALID") from exc

    readonly = client or ReadOnlySupabase()
    before = _snapshot(readonly, source_job_id)
    job = readonly.get_job(source_job_id)
    _require(job.get("status") == "complete" and job.get("stage") == "complete", "SOURCE_JOB_NOT_COMPLETE")
    source_path = validate_source_path(job)
    source_bytes = readonly.download_object(BUCKET, source_path)
    corrections = readonly.get_confirmed_corrections(source_job_id)
    all_correction_count = len(before["corrections"])
    _require(all_correction_count == 39, "LIVE_CORRECTION_COUNT_MISMATCH")
    semantic_path = f"{job['user_id']}/{source_job_id}/internal/semantic.json"
    cached_semantic = readonly.download_json(BUCKET, semantic_path)

    pass1 = _run_replay(job, source_bytes, corrections, cached_semantic)
    _require(not pass1["application_issues"], "PASS1_CORRECTION_APPLICATION_ISSUE")
    pass1_corrections = _validate_correction_overlay(
        pass1["structure"], len(corrections)
    )
    pass1_open = _open_exceptions(pass1["canonical"])
    geometry = [
        item for item in pass1_open
        if item.get("category") == GEOMETRY_CATEGORY
        and GEOMETRY_AFFECTED_ID in (item.get("affected_ids") or [])
    ]
    _require(len(pass1_open) == 1 and len(geometry) == 1, "PASS1_REVIEW_SET_UNEXPECTED")
    _require(pass1["canonical"].get("status") == "needs_review", "PASS1_NOT_REVIEW_REQUIRED")
    _require(pass1["canonical"].get("totals", {}).get("computed") == 150, "PASS1_TOTAL_MISMATCH")
    media = _media_acceptance(pass1["normalized"], pass1["canonical"])

    ephemeral = _ephemeral_geometry_correction(pass1["canonical"])
    pass2 = _run_replay(
        job, source_bytes, [*corrections, ephemeral], cached_semantic
    )
    _require(not pass2["application_issues"], "PASS2_CORRECTION_APPLICATION_ISSUE")
    pass2_corrections = _validate_correction_overlay(
        pass2["structure"], len(corrections) + 1
    )
    _require(not _open_exceptions(pass2["canonical"]), "PASS2_REVIEW_REMAINS")
    _require(pass2["canonical"].get("status") == "render_ready", "PASS2_NOT_RENDER_READY")
    _require(pass2["validation"].get("passed") is True, "PASS2_VALIDATION_FAILED")
    _require(pass2["canonical"].get("totals", {}).get("computed") == 150, "PASS2_TOTAL_MISMATCH")
    _require(
        _non_target_content_fingerprint(pass1["canonical"], GEOMETRY_AFFECTED_ID)
        == _non_target_content_fingerprint(pass2["canonical"], GEOMETRY_AFFECTED_ID),
        "PASS2_CHANGED_UNRELATED_CONTENT",
    )

    with tempfile.TemporaryDirectory(prefix="phase81a-readonly-") as temp_dir:
        rendered = renderer(pass2["canonical"], source_bytes, temp_dir)
        docx_path = Path(rendered["docx_path"])
        pdf_path = Path(rendered["pdf_path"])
        media_counts = _rendered_source_media(docx_path, pass2["canonical"])
        substantive_ids = {
            item["asset_id"] for item in _figure_ownership(pass2["canonical"])
            if item.get("media_class") == "substantive_figure"
        }
        contextual_ids = {
            item["asset_id"] for item in _figure_ownership(pass2["canonical"])
            if item.get("media_class") == "contextual_raster"
        }
        _require(all(media_counts.get(asset_id) == 1 for asset_id in substantive_ids), "RENDERED_SUBSTANTIVE_MEDIA_MISMATCH")
        _require(all(media_counts.get(asset_id) == 1 for asset_id in contextual_ids), "RENDERED_CONTEXTUAL_MEDIA_MISMATCH")
        _require(rendered["docx_preflight"].get("passed") is True, "DOCX_PREFLIGHT_FAILED")
        _require(rendered["pdf_preflight"].get("passed") is True, "PDF_PREFLIGHT_FAILED")
        _require(_cover_page_count_matches(docx_path, int(rendered["page_count"])), "COVER_PAGE_COUNT_MISMATCH")
        q72 = _find_item(pass2["canonical"], "7.2")
        q72_math_count = sum(
            1 for block in _iter_blocks([q72] if q72 else [])
            if block.get("type") == "math"
        )
        _require(q72_math_count > 0, "Q72_NATIVE_MATH_MISSING")
        _require(
            int(rendered["docx_preflight"].get("native_math_elements") or 0)
            >= int(rendered["docx_preflight"].get("expected_math_blocks") or 0),
            "NATIVE_MATH_COUNT_MISMATCH",
        )
        render_summary = {
            "docx_generated": docx_path.exists() and docx_path.stat().st_size > 0,
            "pdf_generated": pdf_path.exists() and pdf_path.stat().st_size > 0,
            "docx_size_bytes": docx_path.stat().st_size,
            "pdf_size_bytes": pdf_path.stat().st_size,
            "docx_preflight_passed": True,
            "pdf_preflight_passed": True,
            "native_math_elements": rendered["docx_preflight"].get("native_math_elements"),
            "expected_math_blocks": rendered["docx_preflight"].get("expected_math_blocks"),
            "page_count": int(rendered["page_count"]),
            "cover_page_count_matches": True,
            "substantive_figures_rendered": len(substantive_ids),
            "contextual_rasters_rendered": len(contextual_ids),
            "duplicate_figure_emission": False,
            "q72_native_math_preserved": True,
        }

    after = _snapshot(readonly, source_job_id)
    _require(before == after, "LIVE_SOURCE_MUTATION_DETECTED")

    report = {
        "source_job_id": source_job_id,
        "source_mutated": False,
        "live_correction_count": all_correction_count,
        "pass1": {
            "review_required": True,
            "geometry_conflicts": 1,
            "exception_categories": [GEOMETRY_CATEGORY],
            "affected_ids": [GEOMETRY_AFFECTED_ID],
            "cache_mode": pass1["cache_mode"],
            "interpreter_run_count": len(pass1["semantic"].get("interpreter_runs", [])),
            "computed_total": 150,
            "correction_history": pass1_corrections,
            **media,
        },
        "pass2": {
            "ephemeral_correction_count": 1,
            "live_corrections_mutated": False,
            "cache_mode": pass2["cache_mode"],
            "interpreter_run_count": len(pass2["semantic"].get("interpreter_runs", [])),
            "render_ready": True,
            "validation_passed": True,
            "computed_total": 150,
            "correction_history": pass2_corrections,
            **render_summary,
        },
        "immutability": {
            "job_state_unchanged": True,
            "correction_state_unchanged": True,
            "event_state_unchanged": True,
            "output_hashes_unchanged": True,
        },
    }
    _assert_sanitized_report(report)
    return report


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "phase81a-replay":
        raise SystemExit(
            "Usage: python -m engine.src.memo_engine.acceptance phase81a-replay <source_job_id>"
        )
    report = run_phase81a_acceptance(args[1])
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
