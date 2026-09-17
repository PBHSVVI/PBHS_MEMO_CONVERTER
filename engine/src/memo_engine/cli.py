from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from .http import SupabaseRest
from .ingestion import IngestionError, ingest_bytes, validate_source_path
from .normalization import NormalizationError, normalize_source

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
        db.add_event(
            failed,
            "worker_failed",
            stage,
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
        extraction = ingestion["extraction"]

        job = db.patch_job(
            job_id,
            "processing",
            {
                "stage": "normalization",
                "source_sha256": source["sha256"],
                "source_size_bytes": source["size_bytes"],
                "engine_version": "phase2.0",
                "updated_at": utc_now(),
            },
        )
        db.add_event(
            job,
            "phase1_ingestion_complete",
            "normalization",
            {
                "detected_kind": source["detected_kind"],
                "detected_mime": source["detected_mime"],
                "size_bytes": source["size_bytes"],
                "sha256": source["sha256"],
                "has_digital_text": extraction["has_digital_text"],
                "text_length": extraction["text_length"],
                "page_count": extraction.get("page_count"),
                "warning_codes": [
                    item["code"] for item in ingestion.get("warnings", [])
                ],
                "ingestion_path": ingestion_path,
            },
        )

        normalized = normalize_source(job, source_bytes, ingestion)
        normalized_path = f"{job['user_id']}/{job['id']}/internal/normalized.json"
        db.upload_json(BUCKET, normalized_path, normalized)

        content = normalized["content"]
        summary = content.get("summary", {})
        ocr = content.get("ocr", {})

        job = db.patch_job(
            job_id,
            "processing",
            {
                "status": "failed_retryable",
                "stage": "phase2_normalized",
                "engine_version": "phase2.0",
                "error_code": "PHASE2_STRUCTURE_NOT_YET_CONNECTED",
                "error_message": (
                    "Deterministic normalisation/local OCR succeeded; "
                    "question and mark structure interpretation is the next milestone."
                ),
                "updated_at": utc_now(),
            },
        )

        db.add_event(
            job,
            "phase2_normalization_complete",
            "phase2_normalized",
            {
                "source_kind": source["detected_kind"],
                "normalized_path": normalized_path,
                "page_count": summary.get("page_count"),
                "unit_count": summary.get("unit_count"),
                "paragraph_count": summary.get("paragraph_count"),
                "table_count": summary.get("table_count"),
                "equation_count": summary.get("equation_count"),
                "embedded_media_count": summary.get("embedded_media_count"),
                "ocr_attempted": ocr.get("attempted", 0),
                "ocr_used": ocr.get("used", 0),
                "ocr_engine": ocr.get("engine"),
            },
        )

        print(
            "Phase 2 normalization verified "
            f"for job {job_id}: kind={source['detected_kind']}, "
            f"ocr_attempted={ocr.get('attempted', 0)}, "
            f"ocr_used={ocr.get('used', 0)}"
        )
        return 0

    except IngestionError as exc:
        fail_processing_job(
            db,
            job,
            code=exc.code,
            message=exc.public_message,
            stage="ingestion_failed",
        )
        raise
    except NormalizationError as exc:
        fail_processing_job(
            db,
            job,
            code=exc.code,
            message=exc.public_message,
            stage="normalization_failed",
        )
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
        print(
            "usage: python -m engine.src.memo_engine.cli run-job <job_id>",
            file=sys.stderr,
        )
        return 2
    return run_job(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
