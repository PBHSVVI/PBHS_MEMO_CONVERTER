from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import PurePosixPath
from typing import Any

from .http import SupabaseRest
from .ai_router import ProviderError, _post_json
from .corrections import apply_confirmed_corrections
from .ingestion import IngestionError, ingest_bytes
from .normalization import NormalizationError, normalize_source
from .phase7_5 import phase7_5_deterministic_proposal
from .structure import flatten_units
from .teacher_language import interpret_teacher_language

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


def _vision_question_candidates(
    image_bytes: bytes,
    mime_type: str,
) -> tuple[list[str], dict[str, Any]]:
    privacy_mode = os.environ.get(
        "MEMO_PRIVACY_MODE", "APPROVED_EXTERNAL_ONLY"
    ).strip().upper()
    approved = {
        part.strip().lower()
        for part in os.environ.get("MEMO_APPROVED_PROVIDERS", "groq").split(",")
        if part.strip()
    }
    key = os.environ.get("GROQ_API_KEY", "").strip()

    if privacy_mode == "LOCAL_ONLY" or "groq" not in approved or not key:
        return [], {
            "used": False,
            "reason": "external_vision_not_configured",
        }

    model = os.environ.get(
        "MEMO_GROQ_VISION_MODEL", "qwen/qwen3.8-27b"
    ).strip() or "qwen/qwen3.8-27b"

    encoded = base64.b64encode(image_bytes).decode("ascii")
    safe_mime = mime_type if mime_type in {"image/jpeg", "image/png"} else "image/jpeg"

    schema = {
        "type": "object",
        "properties": {
            "question_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "transcription": {"type": "string"},
        },
        "required": ["question_ids", "transcription"],
        "additionalProperties": False,
    }

    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "OCR task only. Transcribe every question-number identifier "
                        "that is visibly written in this correction image. "
                        "Examples of the allowed shape are 2.2 and 11.2.1. "
                        "Do not infer, repair, autocomplete, or choose a likely value. "
                        "If a digit or identifier is genuinely unreadable, return an "
                        "empty question_ids array. Return the visible transcription too."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{safe_mime};base64,{encoded}",
                    },
                },
            ],
        }],
        "temperature": 0,
        "reasoning_effort": "none",
        "max_completion_tokens": 256,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "correction_identifier_ocr",
                "strict": True,
                "schema": schema,
            },
        },
    }

    try:
        payload, elapsed_ms = _post_json(
            "https://api.groq.com/openai/v1/chat/completions",
            {"Authorization": f"Bearer {key}"},
            body,
        )
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except ProviderError as exc:
        return [], {
            "used": True,
            "provider": "groq",
            "model": model,
            "error_code": exc.code,
            "error_message": exc.public_message,
        }
    except Exception:
        return [], {
            "used": True,
            "provider": "groq",
            "model": model,
            "error_code": "VISION_RESPONSE_INVALID",
        }

    ids: list[str] = []
    raw_ids = parsed.get("question_ids")
    if isinstance(raw_ids, list):
        for item in raw_ids:
            value = str(item).strip()
            if QUESTION_TOKEN_RE.fullmatch(value) and value not in ids:
                ids.append(value)

    usage = payload.get("usage") or {}
    return ids, {
        "used": True,
        "provider": "groq",
        "model": model,
        "elapsed_ms": elapsed_ms,
        "prompt_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "question_ids": ids,
        "transcription": str(parsed.get("transcription") or "")[:500],
    }


def deterministic_proposal(
    exception: dict[str, Any],
    evidence_text: str,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    category = str(exception.get("category") or "")
    affected = str(exception.get("affected_id") or "").strip()

    phase_proposal, phase_display, phase_evidence = phase7_5_deterministic_proposal(
        exception, evidence_text
    )
    if phase_evidence.get("phase7_5_handled"):
        return phase_proposal, phase_display, phase_evidence

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

        suggested_targets = [
            str(item.get("candidate") or "").strip()
            for item in (exception.get("suggestions") or [])
            if isinstance(item, dict)
            and item.get("kind") == "review_numbering"
            and str(item.get("candidate") or "").strip()
        ]
        if suggested_targets and target not in suggested_targets:
            evidence["deterministic_suggestion_targets"] = suggested_targets
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


def _artifact_json(db: SupabaseRest, path: str) -> dict[str, Any]:
    try:
        value = json.loads(db.download_object(BUCKET, path).decode("utf-8"))
    except Exception as exc:
        raise CorrectionReinterpretationError(
            "CORRECTION_CONTEXT_UNAVAILABLE",
            "The current memo evidence could not be loaded for safe interpretation.",
        ) from exc
    if not isinstance(value, dict):
        raise CorrectionReinterpretationError(
            "CORRECTION_CONTEXT_INVALID",
            "The current memo evidence is not a valid structured artifact.",
        )
    return value


def load_interpretation_context(
    db: SupabaseRest,
    correction: dict[str, Any],
    exception: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    prefix = f"{correction['user_id']}/{correction['job_id']}/internal"
    structure = _artifact_json(db, f"{prefix}/structure.json")
    normalized = _artifact_json(db, f"{prefix}/normalized.json")
    affected = str(exception.get("affected_id") or "")
    questions = [
        item for item in structure.get("questions", [])
        if str(item.get("question_id") or "") == affected
    ]
    current_question = None
    source_excerpt = ""
    if len(questions) == 1:
        question = questions[0]
        current_question = {
            "question_id": question.get("question_id"),
            "printed_marks": question.get("printed_marks"),
            "computed_marks": question.get("computed_shorthand_marks"),
            "mark_calculation_mode": question.get("mark_calculation_mode"),
            "mark_points": (question.get("mark_points") or [])[:20],
        }
        blocks = flatten_units(normalized)
        index = int(question.get("source_block_index", -1))
        if 0 <= index < len(blocks):
            nearby = blocks[max(0, index - 1):min(len(blocks), index + 2)]
            source_excerpt = "\n\n".join(
                " | ".join(str(cell) for cell in block.get("cells", []) if str(cell).strip())
                for block in nearby
            )[:2400]

    job_id = urllib.parse.quote(str(correction["job_id"]), safe="")
    parent_rows = _rows(
        db,
        "/rest/v1/exceptions"
        f"?job_id=eq.{job_id}&category=eq.question_total_mismatch"
        "&status=in.(open,awaiting_reinterpretation,awaiting_confirmation)"
        "&select=affected_id,message",
    )
    parent_discrepancies = [
        {"affected_id": row.get("affected_id"), "message": row.get("message")}
        for row in parent_rows
        if affected.startswith(str(row.get("affected_id") or "") + ".")
    ]
    context = {
        "current_question": current_question,
        "source_excerpt": source_excerpt,
        "parent_discrepancies": parent_discrepancies,
    }
    return structure, normalized, context


def deterministic_proposal_validator(
    structure: dict[str, Any],
    normalized: dict[str, Any],
):
    def validate(proposal: dict[str, Any]) -> tuple[bool, str | None]:
        _, applied, issues = apply_confirmed_corrections(
            structure,
            normalized,
            [{
                "id": "reinterpretation-validation",
                "confirmation_status": "confirmed",
                "confirmed_at": "9999-12-31T23:59:59+00:00",
                "proposed_patch": proposal,
            }],
        )
        if len(applied) == 1 and not issues:
            return True, None
        message = str((issues[0] if issues else {}).get("message") or "")
        return False, message or "The proposal did not pass deterministic correction validation."
    return validate


def interpret_evidence_ladder(
    exception: dict[str, Any],
    evidence_text: str,
    structure: dict[str, Any],
    normalized: dict[str, Any],
    context: dict[str, Any],
    *,
    tier0_result: tuple[
        dict[str, Any] | None,
        str | None,
        dict[str, Any],
    ] | None = None,
    provider=None,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    proposal, display_text, tier0 = tier0_result or deterministic_proposal(
        exception, evidence_text
    )
    validator = deterministic_proposal_validator(structure, normalized)
    if proposal is not None:
        valid, reason = validator(proposal)
        tier0["deterministic_validation"] = {"passed": valid, "message": reason}
        if valid:
            return proposal, display_text, {
                **tier0,
                "status": "resolved",
                "method": proposal.get("reinterpretation_method"),
                "deterministic_resolution_count": 1,
                "fast_model_interpretation_count": 0,
                "strong_model_escalation_count": 0,
                "unresolved_count": 0,
                "runs": [],
            }

    kwargs: dict[str, Any] = {"proposal_validator": validator}
    if provider is not None:
        kwargs["provider"] = provider
    ai_proposal, ai_display, language_audit = interpret_teacher_language(
        exception, evidence_text, context, **kwargs
    )
    return ai_proposal, ai_display, {**tier0, "tier0": tier0, **language_audit}


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
    interpretation_context: dict[str, Any] = {}

    try:
        evidence_text, extraction = extract_evidence_text(db, correction)
        proposal, display_text, tier0 = deterministic_proposal(
            exception, evidence_text
        )
        language_text = evidence_text

        # Tesseract remains the free/local first pass. Handwritten correction
        # evidence is escalated to the approved vision provider only when the
        # deterministic OCR result cannot produce a safe proposal.
        input_kind = str(correction.get("input_kind") or "")
        detected_kind = str(extraction.get("detected_kind") or "")
        if (
            proposal is None
            and input_kind in {"photo", "upload"}
            and detected_kind in {"jpeg", "png"}
        ):
            storage_path = str(correction.get("storage_path") or "")
            blob = db.download_object(BUCKET, storage_path)
            mime_type = str(extraction.get("detected_mime") or "")
            vision_ids, vision = _vision_question_candidates(blob, mime_type)
            extraction["vision_fallback"] = vision
            vision_text = str(vision.get("transcription") or "").strip()
            if vision_text:
                language_text = vision_text

            if vision_ids:
                tesseract_interpretation = tier0
                proposal, display_text, vision_interpretation = deterministic_proposal(
                    exception, "\n".join(vision_ids)
                )
                tier0 = {
                    **vision_interpretation,
                    "local_ocr_candidate_question_ids": (
                        tesseract_interpretation.get("candidate_question_ids") or []
                    ),
                    "vision_candidate_question_ids": vision_ids,
                }
                if proposal is not None:
                    proposal["reinterpretation_method"] = (
                        "groq_vision_ocr_then_deterministic_numbering"
                    )

        structure, normalized, context = load_interpretation_context(
            db, correction, exception
        )
        interpretation_context = {
            "active_exception": {
                "category": exception.get("category"),
                "affected_id": exception.get("affected_id"),
                "message": exception.get("message"),
            },
            "existing_suggestions": (exception.get("suggestions") or [])[:10],
            "source_excerpt": str(context.get("source_excerpt") or "")[:2400],
            "current_question": context.get("current_question"),
            "parent_discrepancies": context.get("parent_discrepancies") or [],
            "teacher_evidence_length": len(language_text),
        }
        proposal, display_text, interpretation = interpret_evidence_ladder(
            exception,
            language_text,
            structure,
            normalized,
            context,
            tier0_result=(proposal, display_text, tier0),
        )
        if proposal is None:
            display_text = (
                "I could not interpret this correction safely yet. "
                "Please edit it with one specific question number, mark total, "
                "or marking instruction, then try again."
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
        "interpretation_context": interpretation_context,
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
                "provider_runs": interpretation.get("runs") or [],
                "escalation_reason": interpretation.get("escalation_reason"),
                "deterministic_validation": interpretation.get("deterministic_validation"),
                "deterministic_resolution_count": interpretation.get(
                    "deterministic_resolution_count", 0
                ),
                "fast_model_interpretation_count": interpretation.get(
                    "fast_model_interpretation_count", 0
                ),
                "strong_model_escalation_count": interpretation.get(
                    "strong_model_escalation_count", 0
                ),
                "unresolved_count": interpretation.get("unresolved_count", 0),
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
            "failure_code": interpretation.get("failure_code"),
            "provider_error": interpretation.get("provider_error"),
            "provider_runs": interpretation.get("runs") or [],
            "escalation_reason": interpretation.get("escalation_reason"),
            "deterministic_resolution_count": interpretation.get(
                "deterministic_resolution_count", 0
            ),
            "fast_model_interpretation_count": interpretation.get(
                "fast_model_interpretation_count", 0
            ),
            "strong_model_escalation_count": interpretation.get(
                "strong_model_escalation_count", 0
            ),
            "unresolved_count": interpretation.get("unresolved_count", 1),
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
        "Phase 7.5 correction reinterpretation: "
        f"{result['correction_id']} -> {result['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
