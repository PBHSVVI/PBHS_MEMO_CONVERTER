from __future__ import annotations

import datetime as dt
import re
import sys
import urllib.parse
from pathlib import PurePosixPath
from typing import Any

from .http import SupabaseRest
from .ingestion import IngestionError, ingest_bytes
from .normalization import NormalizationError, normalize_source

BUCKET = "memo-files"
QUESTION_TOKEN_RE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){1,2})(?![\d.])")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


class CorrectionReinterpretationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _rows(db: SupabaseRest, path: str) -> list[dict[str, Any]]:
    value = db._request_json("GET", path)  # server-side client; never browser-exposed
    return value if isinstance(value, list) else []


def _one(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(rows) != 1:
        raise CorrectionReinterpretationError(
            "CORRECTION_LOOKUP_FAILED",
            f"The {label} could not be resolved uniquely.",
        )
    return rows[0]


def load_bundle(db: SupabaseRest, correction_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cid = urllib.parse.quote(correction_id, safe="")
    correction = _one(
        _rows(
            db,
            "/rest/v1/corrections"
            f"?id=eq.{cid}"
            "&select=id,job_id,user_id,exception_id,input_kind,typed_text,storage_path,display_text,proposed_patch,confirmation_status,created_at,confirmed_at,applied_at",
        ),
        "correction",
    )
    if correction.get("confirmation_status") != "pending":
        raise CorrectionReinterpretationError(
            "CORRECTION_NOT_PENDING",
            "Only a pending correction can be reinterpreted.",
        )

    job_id = urllib.parse.quote(str(correction["job_id"]), safe="")
    exception_id = urllib.parse.quote(str(correction["exception_id"]), safe="")
    job = _one(
        _rows(
            db,
            "/rest/v1/jobs"
            f"?id=eq.{job_id}"
            "&select=id,user_id,status,stage,source_sha256,source_filename",
        ),
        "job",
    )
    exception = _one(
        _rows(
            db,
            "/rest/v1/exceptions"
            f"?id=eq.{exception_id}&job_id=eq.{job_id}"
            "&select=id,job_id,user_id,level,category,affected_id,message,suggestions,status",
        ),
        "exception",
    )

    if str(job.get("user_id")) != str(correction.get("user_id")):
        raise CorrectionReinterpretationError(
            "CORRECTION_TENANT_MISMATCH",
            "Correction ownership does not match the job.",
        )
    if exception.get("status") != "awaiting_reinterpretation":
        raise CorrectionReinterpretationError(
            "EXCEPTION_NOT_AWAITING_REINTERPRETATION",
            "The linked exception is not awaiting reinterpretation.",
        )
    return correction, exception, job


def _normalised_text(normalized: dict[str, Any]) -> str:
    content = normalized.get("content") or {}
    if content.get("units") is not None:
        chunks: list[str] = []
        for unit in content.get("units", []):
            if unit.get("type") == "paragraph":
                chunks.append(str(unit.get("text") or ""))
            elif unit.get("type") == "table":
                for row in unit.get("rows", []):
                    for cell in row:
                        chunks.append(str(cell.get("text") or ""))
        return "\n".join(part for part in chunks if part.strip())
    return "\n".join(
        str(page.get("effective_text") or page.get("text") or "")
        for page in content.get("pages", [])
        if str(page.get("effective_text") or page.get("text") or "").strip()
    )


def extract_evidence_text(
    db: SupabaseRest,
    correction: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    kind = str(correction.get("input_kind") or "")
    if kind == "typed":
        text = str(correction.get("typed_text") or "").strip()
        if not text:
            raise CorrectionReinterpretationError(
                "CORRECTION_TEXT_EMPTY",
                "The typed correction is empty.",
            )
        return text, {
            "method": "typed_text",
            "detected_kind": "text",
            "text_length": len(text),
        }

    if kind not in {"photo", "upload"}:
        raise CorrectionReinterpretationError(
            "CORRECTION_INPUT_KIND_UNSUPPORTED",
            "This correction input kind does not require reinterpretation.",
        )

    storage_path = str(correction.get("storage_path") or "")
    if not storage_path:
        raise CorrectionReinterpretationError(
            "CORRECTION_FILE_MISSING",
            "The correction file path is missing.",
        )

    blob = db.download_object(BUCKET, storage_path)
    filename = PurePosixPath(storage_path).name or "correction.bin"
    fake_id = str(correction["id"])
    fake_job = {
        "id": fake_id,
        "user_id": correction["user_id"],
        "source_path": f"{correction['user_id']}/{fake_id}/source/{filename}",
        "source_filename": filename,
        "source_mime": None,
    }

    try:
        ingestion = ingest_bytes(fake_job, blob)
        normalized = normalize_source(fake_job, blob, ingestion)
    except (IngestionError, NormalizationError) as exc:
        raise CorrectionReinterpretationError(
            "CORRECTION_EVIDENCE_EXTRACTION_FAILED",
            exc.public_message,
        ) from exc

    text = _normalised_text(normalized).strip()
    if not text:
        raise CorrectionReinterpretationError(
            "CORRECTION_EVIDENCE_UNREADABLE",
            "No readable text could be extracted from the correction evidence.",
        )

    source = ingestion.get("source") or {}
    return text, {
        "method": "deterministic_ingestion_normalization",
        "detected_kind": source.get("detected_kind"),
        "detected_mime": source.get("detected_mime"),
        "text_length": len(text),
        "sha256": source.get("sha256"),
    }


def _question_candidates(text: str) -> list[str]:
    seen: list[str] = []
    for match in QUESTION_TOKEN_RE.finditer(text):
        value = match.group(1)
        if value not in seen:
            seen.append(value)
    return seen


def deterministic_proposal(
    exception: dict[str, Any],
    evidence_text: str,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    category = str(exception.get("category") or "")
    affected = str(exception.get("affected_id") or "").strip()
    candidates = _question_candidates(evidence_text)
    evidence = {
        "candidate_question_ids": candidates,
        "candidate_count": len(candidates),
    }
    if len(candidates) != 1:
        return None, None, evidence

    target = candidates[0]
    if category == "unlabeled_mark_bearing_question":
        if affected and target != affected:
            return None, None, evidence
        proposal = {
            "schema_version": "1.0",
            "operation": "promote_unlabeled_question",
            "category": category,
            "affected_id": exception.get("affected_id"),
            "target_id": target,
            "reinterpretation_method": "deterministic_numbering_text",
        }
        return proposal, f"Interpret the unlabelled source row as Question {target}.", evidence

    if category in {"numbering_jump", "suspicious_question_identifier"}:
        if not affected or not QUESTION_TOKEN_RE.fullmatch(affected):
            return None, None, evidence
        source_parts = affected.split(".")
        target_parts = target.split(".")
        if len(source_parts) != len(target_parts) or source_parts[0] != target_parts[0]:
            return None, None, evidence
        if target == affected:
            return None, None, evidence
        proposal = {
            "schema_version": "1.0",
            "operation": "rename_question_identifier",
            "category": category,
            "affected_id": affected,
            "target_id": target,
            "reinterpretation_method": "deterministic_numbering_text",
        }
        return proposal, f"Rename Question {affected} to Question {target}.", evidence

    return None, None, evidence


def _patch_correction(
    db: SupabaseRest,
    correction_id: str,
    values: dict[str, Any],
) -> None:
    cid = urllib.parse.quote(correction_id, safe="")
    rows = db._request_json(
        "PATCH",
        f"/rest/v1/corrections?id=eq.{cid}&confirmation_status=eq.pending",
        body=values,
        prefer="return=representation",
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise CorrectionReinterpretationError(
            "CORRECTION_UPDATE_FAILED",
            "The reinterpretation result could not be stored.",
        )


def reinterpret_correction(correction_id: str) -> dict[str, Any]:
    if not UUID_RE.fullmatch(correction_id):
        raise CorrectionReinterpretationError(
            "CORRECTION_ID_INVALID",
            "Correction identifier is invalid.",
        )

    db = SupabaseRest()
    correction, exception, job = load_bundle(db, correction_id)
    now = utc_now()

    try:
        evidence_text, extraction = extract_evidence_text(db, correction)
        proposal, display_text, interpretation = deterministic_proposal(
            exception, evidence_text
        )
    except CorrectionReinterpretationError as exc:
        extraction = {"method": "failed", "error_code": exc.code}
        proposal = None
        display_text = (
            "The correction evidence could not be reinterpreted safely. "
            "Reject this attempt and provide clearer evidence."
        )
        interpretation = {"error_code": exc.code}

    artifact_path = (
        f"{correction['user_id']}/{correction['job_id']}/corrections/"
        f"{correction_id}/reinterpretation.json"
    )
    artifact = {
        "schema_version": "1.0",
        "phase": "phase7_correction_reinterpretation",
        "correction_id": correction_id,
        "job_id": correction["job_id"],
        "exception_id": correction["exception_id"],
        "input_kind": correction.get("input_kind"),
        "extraction": extraction,
        "interpretation": interpretation,
        "proposal": proposal,
        "confirmation_ready": proposal is not None,
        "created_at": now,
    }
    db.upload_json(BUCKET, artifact_path, artifact)

    if proposal is not None:
        _patch_correction(
            db,
            correction_id,
            {
                "display_text": display_text,
                "proposed_patch": proposal,
                "updated_at": now,
            },
        )
        eid = urllib.parse.quote(str(correction["exception_id"]), safe="")
        db._request_json(
            "PATCH",
            f"/rest/v1/exceptions?id=eq.{eid}&status=eq.awaiting_reinterpretation",
            body={"status": "awaiting_confirmation", "updated_at": now},
            prefer="return=minimal",
        )
        jid = urllib.parse.quote(str(correction["job_id"]), safe="")
        db._request_json(
            "PATCH",
            f"/rest/v1/jobs?id=eq.{jid}&status=eq.correction_pending",
            body={
                "stage": "phase7_awaiting_confirmation",
                "review_required": True,
                "updated_at": now,
            },
            prefer="return=minimal",
        )
        db.add_event(
            job,
            "phase7_correction_reinterpreted",
            "phase7_awaiting_confirmation",
            {
                "correction_id": correction_id,
                "exception_id": correction["exception_id"],
                "input_kind": correction.get("input_kind"),
                "method": proposal.get("reinterpretation_method"),
                "operation": proposal.get("operation"),
                "target_id": proposal.get("target_id"),
                "artifact_path": artifact_path,
            },
        )
        return {
            "status": "awaiting_confirmation",
            "correction_id": correction_id,
            "proposal": proposal,
            "artifact_path": artifact_path,
        }

    _patch_correction(
        db,
        correction_id,
        {
            "display_text": display_text,
            "proposed_patch": None,
            "updated_at": now,
        },
    )
    db.add_event(
        job,
        "phase7_correction_reinterpretation_unresolved",
        "phase7_awaiting_reinterpretation",
        {
            "correction_id": correction_id,
            "exception_id": correction["exception_id"],
            "input_kind": correction.get("input_kind"),
            "artifact_path": artifact_path,
            "candidate_count": interpretation.get("candidate_count"),
            "error_code": interpretation.get("error_code"),
        },
    )
    return {
        "status": "awaiting_reinterpretation",
        "correction_id": correction_id,
        "proposal": None,
        "artifact_path": artifact_path,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Usage: python -m engine.src.memo_engine.correction_reinterpretation <correction_uuid>", file=sys.stderr)
        return 2
    try:
        result = reinterpret_correction(args[0])
    except CorrectionReinterpretationError as exc:
        print(f"{exc.code}: {exc.public_message}", file=sys.stderr)
        return 1
    print(
        "Phase 7.2 correction reinterpretation: "
        f"{result['correction_id']} -> {result['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
