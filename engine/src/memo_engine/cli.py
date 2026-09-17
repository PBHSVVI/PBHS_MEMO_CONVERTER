from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from .http import SupabaseRest
from .ingestion import IngestionError, ingest_bytes, validate_source_path
from .normalization import NormalizationError, normalize_source
from .structure import extract_structure

BUCKET = "memo-files"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fail_processing_job(
    db: SupabaseRest,
    job: dict[str, Any],
    *,
    code: str,
    message: str,
    stage: str,
) -> None:
    try:
        failed = db.patch_job(
            job["id"],
            "processing",
            {
                "status": "failed_retryable",
                "stage": stage,
                "error_code": code,
                "error_message": message,
                "updated_at": utc_now(),
            },
        )
        db.add_event(failed, "worker_failed", stage, {"error_code": code})
    except Exception:
        pass


def run_job(job_id: str) -> int:
    db = SupabaseRest()
    job = db.get_job(job_id)

    if job["status"] != "dispatched":
        raise RuntimeError(f"Job is not dispatchable from state {job['status']!r}")

    job = db.patch_job(
        job_id,
        "dispatched",
        {
            "status": "processing",
            "stage": "ingestion",
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "error_code": None,
            "error_message": None,
        },
    )
    db.add_event(job, "worker_started", "ingestion")

    try:
        source_path = validate_source_path(job)
        source_bytes = db.download_object(BUCKET, source_path)

        ingestion = ingest_bytes(job, source_bytes)
        ingestion_path = f"{job['user_id']}/{job['id']}/internal/ingestion.json"
        db.upload_json(BUCKET, ingestion_path, ingestion)

        source = ingestion["source"]
        job = db.patch_job(
            job_id,
            "processing",
            {
                "stage": "normalization",
                "source_sha256": source["sha256"],
                "source_size_bytes": source["size_bytes"],
                "engine_version": "phase3.1",
                "updated_at": utc_now(),
            },
        )

        normalized = normalize_source(job, source_bytes, ingestion)
        normalized_path = f"{job['user_id']}/{job['id']}/internal/normalized.json"
        db.upload_json(BUCKET, normalized_path, normalized)

        job = db.patch_job(
            job_id,
            "processing",
            {
                "stage": "structure",
                "updated_at": utc_now(),
            },
        )

        structure = extract_structure(normalized)
        structure_path = f"{job['user_id']}/{job['id']}/internal/structure.json"
        db.upload_json(BUCKET, structure_path, structure)

        db.add_exceptions(job, structure["exceptions"])

        summary = structure["summary"]
        review_required = summary["review_required"]
        final_status = "needs_review" if review_required else "failed_retryable"
        error_code = (
            "PHASE3_REVIEW_REQUIRED"
            if review_required
            else "PHASE3_SEMANTIC_INTERPRETATION_NOT_YET_CONNECTED"
        )
        error_message = (
            "Deterministic structure extraction found exceptions requiring teacher review."
            if review_required
            else "Deterministic structure extraction succeeded with no exceptions; semantic interpretation is the next milestone."
        )

        job = db.patch_job(
            job_id,
            "processing",
            {
                "status": final_status,
                "stage": "phase3_structured",
                "review_required": review_required,
                "engine_version": "phase3.1",
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": utc_now(),
            },
        )

        db.add_event(
            job,
            "phase3_structure_complete",
            "phase3_structured",
            {
                "structure_path": structure_path,
                "detected_identifier_count": summary["detected_identifier_count"],
                "leaf_question_count": summary["leaf_question_count"],
                "unique_question_count": summary["unique_question_count"],
                "subtotal_count": summary["subtotal_count"],
                "subtotal_sum": summary["subtotal_sum"],
                "amber_count": summary["amber_count"],
                "red_count": summary["red_count"],
                "review_required": review_required,
            },
        )

        print(
            "Phase 3 structure verified "
            f"for job {job_id}: identifiers={summary['detected_identifier_count']}, "
            f"leaf_questions={summary['leaf_question_count']}, "
            f"amber={summary['amber_count']}, red={summary['red_count']}"
        )
        return 0

    except IngestionError as exc:
        fail_processing_job(db, job, code=exc.code, message=exc.public_message, stage="ingestion_failed")
        raise
    except NormalizationError as exc:
        fail_processing_job(db, job, code=exc.code, message=exc.public_message, stage="normalization_failed")
        raise
    except Exception:
        fail_processing_job(
            db,
            job,
            code="WORKER_INTERNAL_ERROR",
            message="An unexpected error occurred in the hosted deterministic worker.",
            stage="worker_failed",
        )
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "run-job":
        print("usage: python -m engine.src.memo_engine.cli run-job <job_id>", file=sys.stderr)
        return 2
    return run_job(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
