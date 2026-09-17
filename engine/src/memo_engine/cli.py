from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from .http import SupabaseRest
from .ingestion import IngestionError, ingest_bytes, validate_source_path

BUCKET = "memo-files"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fail_processing_job(
    db: SupabaseRest,
    job: dict[str, Any],
    *,
    code: str,
    message: str,
) -> None:
    try:
        failed = db.patch_job(
            job["id"],
            "processing",
            {
                "status": "failed_retryable",
                "stage": "ingestion_failed",
                "error_code": code,
                "error_message": message,
                "updated_at": utc_now(),
            },
        )
        db.add_event(
            failed,
            "ingestion_failed",
            "ingestion_failed",
            {"error_code": code},
        )
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
        },
    )
    db.add_event(job, "worker_started", "ingestion")

    try:
        source_path = validate_source_path(job)
        source_bytes = db.download_object(BUCKET, source_path)
        ingestion = ingest_bytes(job, source_bytes)

        internal_path = f"{job['user_id']}/{job['id']}/internal/ingestion.json"
        db.upload_json(BUCKET, internal_path, ingestion)

        source = ingestion["source"]
        extraction = ingestion["extraction"]
        warnings = ingestion["warnings"]

        job = db.patch_job(
            job_id,
            "processing",
            {
                "status": "failed_retryable",
                "stage": "phase1_ingested",
                "source_sha256": source["sha256"],
                "source_size_bytes": source["size_bytes"],
                "engine_version": "phase1.0",
                "error_code": "PHASE1_DOWNSTREAM_NOT_YET_CONNECTED",
                "error_message": (
                    "Deterministic ingestion succeeded; OCR/interpretation is the next milestone."
                ),
                "updated_at": utc_now(),
            },
        )

        db.add_event(
            job,
            "phase1_ingestion_complete",
            "phase1_ingested",
            {
                "detected_kind": source["detected_kind"],
                "detected_mime": source["detected_mime"],
                "size_bytes": source["size_bytes"],
                "sha256": source["sha256"],
                "has_digital_text": extraction["has_digital_text"],
                "text_length": extraction["text_length"],
                "page_count": extraction.get("page_count"),
                "warning_codes": [item["code"] for item in warnings],
                "ingestion_path": internal_path,
            },
        )

        print(
            "Phase 1 ingestion verified "
            f"for job {job_id}: {source['detected_kind']}, "
            f"{source['size_bytes']} bytes, "
            f"digital_text={extraction['has_digital_text']}"
        )
        return 0

    except IngestionError as exc:
        fail_processing_job(
            db,
            job,
            code=exc.code,
            message=exc.public_message,
        )
        raise
    except Exception:
        fail_processing_job(
            db,
            job,
            code="INGESTION_INTERNAL_ERROR",
            message="An unexpected error occurred during deterministic ingestion.",
        )
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "run-job":
        print(
            "usage: python -m engine.src.memo_engine.cli run-job <job_id>",
            file=sys.stderr,
        )
        return 2
    return run_job(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
