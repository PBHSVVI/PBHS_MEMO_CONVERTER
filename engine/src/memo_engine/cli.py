from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from .ai_router import ProviderError
from .http import SupabaseRest
from .ingestion import IngestionError, ingest_bytes, validate_source_path
from .normalization import NormalizationError, normalize_source
from .semantic import interpret_semantics
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
                "engine_version": "phase4.0",
                "updated_at": utc_now(),
            },
        )

        normalized = normalize_source(job, source_bytes, ingestion)
        normalized_path = f"{job['user_id']}/{job['id']}/internal/normalized.json"
        db.upload_json(BUCKET, normalized_path, normalized)

        job = db.patch_job(
            job_id,
            "processing",
            {"stage": "structure", "updated_at": utc_now()},
        )
        structure = extract_structure(normalized)
        structure_path = f"{job['user_id']}/{job['id']}/internal/structure.json"
        db.upload_json(BUCKET, structure_path, structure)

        structural_exceptions = structure["exceptions"]
        db.add_exceptions(job, structural_exceptions)

        job = db.patch_job(
            job_id,
            "processing",
            {"stage": "semantic_interpretation", "updated_at": utc_now()},
        )

        semantic = interpret_semantics(structure)
        semantic_path = f"{job['user_id']}/{job['id']}/internal/semantic.json"
        db.upload_json(BUCKET, semantic_path, semantic)

        semantic_exceptions = semantic["exceptions"]
        db.add_exceptions(job, semantic_exceptions)

        for run in semantic["interpreter_runs"]:
            db.add_event(
                job,
                "phase4_interpreter_run",
                "semantic_interpretation",
                {
                    "provider": run["provider"],
                    "model": run["model"],
                    "candidate_count": run["candidate_count"],
                    "prompt_tokens": run["prompt_tokens"],
                    "output_tokens": run["output_tokens"],
                    "total_tokens": run["total_tokens"],
                    "elapsed_ms": run["elapsed_ms"],
                    "privacy_mode": semantic["privacy_mode"],
                },
            )

        summary = semantic["summary"]
        review_required = bool(structural_exceptions or semantic_exceptions)

        final_status = "needs_review" if review_required else "failed_retryable"
        error_code = (
            "PHASE4_REVIEW_REQUIRED"
            if review_required
            else "PHASE4_MATH_CANONICALIZATION_NOT_YET_CONNECTED"
        )
        error_message = (
            "Semantic interpretation completed; unresolved deterministic or semantic exceptions require teacher review."
            if review_required
            else "Semantic interpretation passed; canonical mathematics and full memo schema assembly are the next milestone."
        )

        job = db.patch_job(
            job_id,
            "processing",
            {
                "status": final_status,
                "stage": "phase4_semantic_interpreted",
                "review_required": review_required,
                "engine_version": "phase4.0",
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": utc_now(),
            },
        )

        db.add_event(
            job,
            "phase4_semantic_complete",
            "phase4_semantic_interpreted",
            {
                "semantic_path": semantic_path,
                "structure_path": structure_path,
                "structural_exception_count": len(structural_exceptions),
                "semantic_exception_count": len(semantic_exceptions),
                "mark_points_total": summary["mark_points_total"],
                "deterministic_count": summary["deterministic_count"],
                "ai_candidate_count": summary["ai_candidate_count"],
                "ai_resolved_green_count": summary["ai_resolved_green_count"],
                "interpreter_run_count": summary["interpreter_run_count"],
                "review_required": review_required,
            },
        )

        print(
            "Phase 4 semantic interpretation verified "
            f"for job {job_id}: deterministic={summary['deterministic_count']}, "
            f"ai_candidates={summary['ai_candidate_count']}, "
            f"semantic_exceptions={summary['semantic_exception_count']}"
        )
        return 0

    except IngestionError as exc:
        fail_processing_job(
            db, job, code=exc.code, message=exc.public_message, stage="ingestion_failed"
        )
        raise
    except NormalizationError as exc:
        fail_processing_job(
            db, job, code=exc.code, message=exc.public_message, stage="normalization_failed"
        )
        raise
    except ProviderError as exc:
        fail_processing_job(
            db,
            job,
            code=f"PHASE4_{exc.code}",
            message=exc.public_message,
            stage="semantic_provider_failed",
        )
        raise
    except Exception:
        fail_processing_job(
            db,
            job,
            code="WORKER_INTERNAL_ERROR",
            message="An unexpected error occurred in the hosted memo worker.",
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
