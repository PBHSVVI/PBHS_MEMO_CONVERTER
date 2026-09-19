from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .ai_router import ProviderError
from .http import SupabaseRest
from .ingestion import IngestionError, ingest_bytes, validate_source_path
from .normalization import NormalizationError, normalize_source
from .semantic import build_semantic_plan, interpret_semantics
from .structure import extract_structure
from .renderer import (
    RENDERER_VERSION,
    RENDER_PROFILE,
    RenderingError,
    render_outputs,
)
from .canonical import (
    CanonicalizationError,
    _iter_blocks,
    _iter_marks,
    build_canonical_memo,
)

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


def _semantic_signature(structure: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    deterministic, candidates = build_semantic_plan(structure)
    result: dict[str, tuple[Any, ...]] = {}
    for item in deterministic + candidates:
        cid = str(item.get("candidate_id"))
        result[cid] = (
            str(item.get("question_id")),
            int(item.get("mark_index") or 0),
            int(item.get("count") or 0),
            item.get("source_shorthand"),
            str(item.get("descriptor") or ""),
        )
    return result


def _cached_semantic_matches(
    structure: dict[str, Any],
    cached: dict[str, Any],
) -> bool:
    if not isinstance(cached, dict) or cached.get("phase") != "phase4_semantics":
        return False
    expected = _semantic_signature(structure)
    observed: dict[str, tuple[Any, ...]] = {}
    for item in cached.get("deterministic_results", []) + cached.get("ai_results", []):
        try:
            cid = str(item["candidate_id"])
            observed[cid] = (
                str(item["question_id"]),
                int(item["mark_index"]),
                int(item.get("count") or 0),
                item.get("source_shorthand"),
                str(item.get("descriptor") or ""),
            )
        except Exception:
            return False
    return bool(expected) and expected == observed


def _try_reuse_semantic(
    db: SupabaseRest,
    job: dict[str, Any],
    structure: dict[str, Any],
    source_sha256: str,
) -> tuple[dict[str, Any] | None, str | None]:
    for candidate_job in db.find_reusable_semantic_jobs(
        user_id=str(job["user_id"]),
        source_sha256=source_sha256,
        exclude_job_id=str(job["id"]),
    ):
        source_job_id = str(candidate_job.get("id") or "")
        if not source_job_id:
            continue
        path = f"{job['user_id']}/{source_job_id}/internal/semantic.json"
        try:
            cached = db.download_json(BUCKET, path)
        except Exception:
            continue
        if not _cached_semantic_matches(structure, cached):
            continue

        reused = dict(cached)
        reused["job_id"] = job["id"]
        reused["interpreter_runs"] = []
        reused["cache"] = {
            "reused": True,
            "source_job_id": source_job_id,
            "source_sha256": source_sha256,
        }
        summary = dict(reused.get("summary") or {})
        summary["interpreter_run_count"] = 0
        reused["summary"] = summary
        return reused, source_job_id
    return None, None


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
                "engine_version": "phase6.0",
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

        semantic, semantic_cache_job_id = _try_reuse_semantic(
            db, job, structure, source["sha256"]
        )
        if semantic is None:
            semantic = interpret_semantics(structure)
        else:
            db.add_event(
                job,
                "phase4_semantic_cache_hit",
                "semantic_interpretation",
                {
                    "source_job_id": semantic_cache_job_id,
                    "source_sha256": source["sha256"],
                    "candidate_count": semantic.get("summary", {}).get(
                        "ai_candidate_count"
                    ),
                },
            )

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
        semantic_review_required = bool(
            structural_exceptions or semantic_exceptions
        )

        # Preserve the Phase 4 component audit inside the Phase 5 pipeline.
        db.add_event(
            job,
            "phase4_semantic_complete",
            "semantic_interpretation",
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
                "semantic_cache_hit": semantic_cache_job_id is not None,
                "review_required": semantic_review_required,
            },
        )

        job = db.patch_job(
            job_id,
            "processing",
            {
                "stage": "canonicalization",
                "engine_version": "phase6.0",
                "updated_at": utc_now(),
            },
        )

        canonical, validation, canonical_exceptions = build_canonical_memo(
            job,
            ingestion,
            normalized,
            structure,
            semantic,
            source_bytes,
        )
        canonical_path = (
            f"{job['user_id']}/{job['id']}/internal/canonical.json"
        )
        validation_path = (
            f"{job['user_id']}/{job['id']}/internal/validation.json"
        )
        db.upload_json(BUCKET, canonical_path, canonical)
        db.upload_json(BUCKET, validation_path, validation)

        # Structural and semantic exceptions were already persisted at their
        # respective stages. Persist only Phase 5 canonical/validation findings.
        db.add_exceptions(job, canonical_exceptions)

        math_block_count = sum(
            1
            for question in canonical.get("questions", [])
            for block in _iter_blocks(question.get("items", []))
            if block.get("type") == "math"
        )
        marking_point_count = sum(
            1
            for question in canonical.get("questions", [])
            for _ in _iter_marks(question.get("items", []))
        )

        render_ready = (
            canonical.get("status") == "render_ready"
            and bool(validation.get("handoff_ready"))
        )
        review_required = not render_ready

        if review_required:
            final_status = "needs_review"
            final_stage = "phase5_canonicalized"
            error_code = "PHASE5_REVIEW_REQUIRED"
            error_message = (
                "Canonical mathematics and interpretation-schema assembly "
                "completed, but deterministic or evidence-linked exceptions "
                "require teacher review."
            )

            job = db.patch_job(
                job_id,
                "processing",
                {
                    "status": final_status,
                    "stage": final_stage,
                    "review_required": True,
                    "engine_version": "phase6.0",
                    "error_code": error_code,
                    "error_message": error_message,
                    "updated_at": utc_now(),
                },
            )

            db.add_event(
                job,
                "phase5_canonical_complete",
                final_stage,
                {
                    "canonical_path": canonical_path,
                    "validation_path": validation_path,
                    "canonical_status": canonical.get("status"),
                    "question_count": len(canonical.get("questions", [])),
                    "math_block_count": math_block_count,
                    "marking_point_count": marking_point_count,
                    "computed_total": canonical.get("totals", {}).get("computed"),
                    "observed_total": canonical.get("totals", {}).get("observed"),
                    "new_exception_count": len(canonical_exceptions),
                    "total_exception_count": len(canonical.get("exceptions", [])),
                    "validation_passed": bool(validation.get("passed")),
                    "core_invariants_passed": bool(
                        validation.get("core_invariants_passed")
                    ),
                    "validation_issue_count": int(
                        validation.get("issue_count") or 0
                    ),
                    "render_ready": False,
                    "review_required": True,
                },
            )

            print(
                "Phase 6 stopped safely before rendering "
                f"for job {job_id}: canonical_status={canonical.get('status')}, "
                f"phase5_exceptions={len(canonical_exceptions)}"
            )
            return 0

        # Record the successful Phase 5 handoff before entering deterministic
        # rendering. This is an audit boundary, not a terminal job state.
        db.add_event(
            job,
            "phase5_canonical_complete",
            "phase5_render_ready",
            {
                "canonical_path": canonical_path,
                "validation_path": validation_path,
                "canonical_status": canonical.get("status"),
                "question_count": len(canonical.get("questions", [])),
                "math_block_count": math_block_count,
                "marking_point_count": marking_point_count,
                "computed_total": canonical.get("totals", {}).get("computed"),
                "observed_total": canonical.get("totals", {}).get("observed"),
                "new_exception_count": len(canonical_exceptions),
                "total_exception_count": len(canonical.get("exceptions", [])),
                "validation_passed": bool(validation.get("passed")),
                "core_invariants_passed": bool(
                    validation.get("core_invariants_passed")
                ),
                "validation_issue_count": int(
                    validation.get("issue_count") or 0
                ),
                "render_ready": True,
                "review_required": False,
            },
        )

        job = db.patch_job(
            job_id,
            "processing",
            {
                "stage": "rendering",
                "review_required": False,
                "engine_version": "phase6.0",
                "error_code": None,
                "error_message": None,
                "updated_at": utc_now(),
            },
        )

        output_docx_path = f"{job['user_id']}/{job['id']}/output/memo.docx"
        output_pdf_path = f"{job['user_id']}/{job['id']}/output/memo.pdf"
        render_validation_path = (
            f"{job['user_id']}/{job['id']}/internal/render_validation.json"
        )

        with tempfile.TemporaryDirectory(prefix=f"pbhs-render-{job_id}-") as td:
            td_path = Path(td)
            try:
                rendered = render_outputs(canonical, source_bytes, td_path)
            except RenderingError as exc:
                diagnostic_root = (
                    f"{job['user_id']}/{job['id']}/internal/render_failure"
                )
                diagnostic_docx_path = diagnostic_root + "/memo.docx"
                diagnostic_pdf_path = diagnostic_root + "/memo.pdf"
                diagnostic_json_path = diagnostic_root + "/preflight.json"

                diagnostic_docx = td_path / "memo.docx"
                diagnostic_pdf = td_path / "memo.pdf"

                uploaded_docx = False
                uploaded_pdf = False

                if diagnostic_docx.exists() and diagnostic_docx.stat().st_size:
                    try:
                        db.upload_object(
                            BUCKET,
                            diagnostic_docx_path,
                            diagnostic_docx.read_bytes(),
                            content_type=(
                                "application/vnd.openxmlformats-officedocument."
                                "wordprocessingml.document"
                            ),
                        )
                        uploaded_docx = True
                    except Exception:
                        pass

                if diagnostic_pdf.exists() and diagnostic_pdf.stat().st_size:
                    try:
                        db.upload_object(
                            BUCKET,
                            diagnostic_pdf_path,
                            diagnostic_pdf.read_bytes(),
                            content_type="application/pdf",
                        )
                        uploaded_pdf = True
                    except Exception:
                        pass

                diagnostic_payload = {
                    "schema_version": "1.0",
                    "phase": "phase6_render_failure",
                    "job_id": job_id,
                    "renderer_version": RENDERER_VERSION,
                    "render_profile": RENDER_PROFILE,
                    "error_code": exc.code,
                    "message": exc.public_message,
                    "details": exc.details,
                    "diagnostic_docx_path": (
                        diagnostic_docx_path if uploaded_docx else None
                    ),
                    "diagnostic_pdf_path": (
                        diagnostic_pdf_path if uploaded_pdf else None
                    ),
                }
                try:
                    db.upload_json(
                        BUCKET,
                        diagnostic_json_path,
                        diagnostic_payload,
                    )
                except Exception:
                    diagnostic_json_path = None

                try:
                    db.add_event(
                        job,
                        "phase6_render_failed",
                        "rendering_failed",
                        {
                            "error_code": exc.code,
                            "issues": list(exc.details.get("issues", [])),
                            "diagnostic_docx_path": (
                                diagnostic_docx_path if uploaded_docx else None
                            ),
                            "diagnostic_pdf_path": (
                                diagnostic_pdf_path if uploaded_pdf else None
                            ),
                            "diagnostic_json_path": diagnostic_json_path,
                        },
                    )
                except Exception:
                    pass

                db.add_exceptions(
                    job,
                    [{
                        "level": "red",
                        "category": "rendering_failure",
                        "affected_id": None,
                        "message": exc.public_message,
                        "suggestions": [],
                    }],
                )
                raise

            docx_bytes = Path(rendered["docx_path"]).read_bytes()
            pdf_bytes = Path(rendered["pdf_path"]).read_bytes()
            docx_sha = hashlib.sha256(docx_bytes).hexdigest()
            pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

            db.upload_object(
                BUCKET,
                output_docx_path,
                docx_bytes,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )
            db.upload_object(
                BUCKET,
                output_pdf_path,
                pdf_bytes,
                content_type="application/pdf",
            )

            render_validation = {
                "schema_version": "1.0",
                "phase": "phase6_render_validation",
                "job_id": job_id,
                "renderer_version": RENDERER_VERSION,
                "render_profile": RENDER_PROFILE,
                "source_schema_version": canonical.get("schema_version"),
                "canonical_status": canonical.get("status"),
                "page_count": rendered["page_count"],
                "docx": {
                    "path": output_docx_path,
                    "size_bytes": len(docx_bytes),
                    "sha256": docx_sha,
                    "preflight": rendered["docx_preflight"],
                },
                "pdf": {
                    "path": output_pdf_path,
                    "size_bytes": len(pdf_bytes),
                    "sha256": pdf_sha,
                    "preflight": rendered["pdf_preflight"],
                },
                "passed": bool(
                    rendered["docx_preflight"].get("passed")
                    and rendered["pdf_preflight"].get("passed")
                ),
            }
            db.upload_json(BUCKET, render_validation_path, render_validation)

        job = db.patch_job(
            job_id,
            "processing",
            {
                "status": "complete",
                "stage": "complete",
                "review_required": False,
                "engine_version": "phase6.0",
                "error_code": None,
                "error_message": None,
                "updated_at": utc_now(),
            },
        )

        db.add_event(
            job,
            "phase6_render_complete",
            "complete",
            {
                "renderer_version": RENDERER_VERSION,
                "render_profile": RENDER_PROFILE,
                "canonical_path": canonical_path,
                "render_validation_path": render_validation_path,
                "docx_path": output_docx_path,
                "pdf_path": output_pdf_path,
                "docx_sha256": docx_sha,
                "pdf_sha256": pdf_sha,
                "docx_size_bytes": len(docx_bytes),
                "pdf_size_bytes": len(pdf_bytes),
                "page_count": render_validation["page_count"],
                "docx_preflight_passed": bool(
                    render_validation["docx"]["preflight"].get("passed")
                ),
                "pdf_preflight_passed": bool(
                    render_validation["pdf"]["preflight"].get("passed")
                ),
                "computed_total": canonical.get("totals", {}).get("computed"),
            },
        )

        print(
            "Phase 6 deterministic rendering completed "
            f"for job {job_id}: pages={render_validation['page_count']}, "
            f"total={canonical.get('totals', {}).get('computed')}, "
            f"renderer={RENDERER_VERSION}"
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
    except RenderingError as exc:
        fail_processing_job(
            db,
            job,
            code=f"PHASE6_{exc.code}",
            message=exc.public_message,
            stage="rendering_failed",
        )
        raise
    except CanonicalizationError as exc:
        fail_processing_job(
            db,
            job,
            code=f"PHASE5_{exc.code}",
            message=exc.public_message,
            stage="canonicalization_failed",
        )
        raise
    except ProviderError as exc:
        fail_processing_job(
            db,
            job,
            code=f"PHASE5_{exc.code}",
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
