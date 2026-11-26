"""Audited, inference-free visual replay for the authorised Phase 8.5 pilot."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import urllib.parse
from typing import Any

from .http import SupabaseRest
from .openai_credit import MODEL, PBHS_URL, PILOT_JOB
from .visual_coordinates import OPENAI_COORDINATE_CONTRACT, openai_crop_pixels
from .visual_evidence import (
    OWNERSHIP_ALGORITHM_VERSION, _render_regions, ensure_visual_evidence_ids,
    validate_visual_response,
)


def rebuild_visual_checkpoint(record: dict, source_bytes: bytes, normalized: dict) -> dict:
    """Recompute ownership from original coordinates, never from effective flags.

    Legacy v1 Luna checkpoints retained the response's seven observation fields
    (including the unmodified bbox and model_normalized_math), but not the full
    transport response. Their reconstruction is labelled as such; the original
    result digest remains on its unchanged run and in the archived checkpoint.
    """
    if (record.get("ownership_algorithm_version") != OWNERSHIP_ALGORITHM_VERSION
            or hashlib.sha256(source_bytes).hexdigest() != record.get("source_sha256")):
        raise ValueError("Checkpoint source or ownership generation differs")
    runs = record.get("runs") or []
    if not runs or any(r.get("success") is not True for r in runs):
        raise ValueError("Replay requires a complete successful checkpoint")
    regions = {r["asset_path"]: r for r in _render_regions(source_bytes, normalized)}
    if len(regions) != len(runs) or len({r["region_id"] for r in runs}) != len(runs):
        raise ValueError("Checkpoint region coverage differs")
    assets = {a["path"]: a for a in record["assets"]}
    result = copy.deepcopy(record)
    responses = {r["region_id"]: r for r in record.get("coordinate_responses") or []}
    before = sum(bool(e.get("effective", True)) for e in record["evidence"])
    recovered = 0
    for run in runs:
        ref = run["region_id"]
        region = regions[ref]
        digest = hashlib.sha256(region["image_bytes"]).hexdigest()
        if (run.get("source_digest") != record["source_sha256"]
                or run.get("crop_digest") != digest or assets[ref]["sha256"] != digest):
            raise ValueError("Saved source crop identity differs")
        if run.get("provider") != "openai":
            continue  # Preserve the six established Groq/Cloudflare checkpoints verbatim.
        if run.get("model") != MODEL or run.get("task_prompt_version") != "visual-evidence-v1":
            raise ValueError("Unknown saved OpenAI coordinate contract")
        observations = {field: [e for e in record[field] if e.get("rendered_asset_ref") == ref]
                        for field in ("evidence", "mark_changes")}
        if any(e.get("extractor_provider") != "openai" for items in observations.values() for e in items):
            raise ValueError("Mixed provenance within one response")
        saved = responses.get(ref)
        if saved:
            if saved.get("crop_digest") != digest:
                raise ValueError("Saved coordinate response crop differs")
            raw = saved["provenance"]["provider_response"]
        else:
            raw = {"schema_version": "1.0", "page": region["page"],
                   "visual_content_present": True, "warnings": []}
            for field, items in observations.items():
                keys = ({"question_ref", "kind", "transcription", "normalized_math", "confidence", "source", "bbox"}
                        if field == "evidence" else
                        {"question_ref", "level", "printed_value", "visual_value", "confidence", "requires_confirmation", "bbox"})
                raw[field] = []
                for item in items:
                    if item.get("coordinate_contract") is not None:
                        raise ValueError("Tagged response lost its original provenance")
                    value = {key: copy.deepcopy(item[key]) for key in keys}
                    if field == "evidence":
                        value["normalized_math"] = item["model_normalized_math"]
                    raw[field].append(value)
        converted = openai_crop_pixels(raw, region["pixel_width"], region["pixel_height"])
        validated = validate_visual_response({**converted, "provider": "openai", "model": MODEL}, region)
        for field, old in observations.items():
            if len(old) != len(validated[field]):
                raise ValueError("Original observation coverage differs")
            replacements = []
            for prior, item in zip(old, validated[field]):
                # Never silently replace original readings during a coordinate repair.
                if field == "evidence" and item["transcription"] != prior["transcription"]:
                    raise ValueError("Saved provider transcription differs")
                item["original_evidence_id"] = prior.get("original_evidence_id", prior.get("evidence_id"))
                replacements.append(item)
            ensure_visual_evidence_ids(replacements)
            positions = [i for i, item in enumerate(result[field]) if item.get("rendered_asset_ref") == ref]
            for position, item in zip(positions, replacements):
                result[field][position] = item
        responses[ref] = {
            "region_id": ref, "crop_digest": digest, "original_result_digest": run["result_digest"],
            "recovery_basis": saved.get("recovery_basis", "original_provider_response") if saved else "saved_provider_observations",
            "provenance": converted["coordinate_provenance"],
        }
        recovered += 1
    result["coordinate_responses"] = list(responses.values())
    audit = result.setdefault("coordinate_revalidation", {
        "contract": OPENAI_COORDINATE_CONTRACT, "effective_before": before,
    })
    audit.update({"recovered_openai_regions": recovered, "visual_inference_calls": 0})
    summary = result["summary"]
    summary.update({"vision_calls": 0, "reused_success_count": len(runs), "new_success_count": 0,
                    "retried_region_count": 0, "partial_checkpoint_reuse": True,
                    "effective_evidence_count": sum(bool(e.get("effective", True)) for e in result["evidence"]),
                    "suppressed_evidence_count": sum(not e.get("effective", True) for e in result["evidence"])})
    return result


def revalidate_job(job_id: str, db: Any = None) -> int:
    from .cli import BUCKET, PHASE85_SAVED_REGIONS, PHASE85_SOURCE_SHA256, run_job, utc_now
    from .ingestion import validate_source_path
    if job_id != PILOT_JOB:
        raise ValueError("Coordinate revalidation is limited to the authorised pilot")
    db = db or SupabaseRest()
    if db.base != PBHS_URL:
        raise ValueError("Coordinate revalidation project differs")
    run_id, attempt = os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if (not re.fullmatch(r"\d+", run_id) or not re.fullmatch(r"\d+", attempt)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != "PBHSVVI/PBHS_MEMO_CONVERTER"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_WORKFLOW") != "Process Memo"):
        raise ValueError("An authenticated hosted workflow run is required")
    job = db.get_job(job_id)
    if (job["status"] != "needs_review" or job["stage"] != "phase5_canonicalized"
            or job.get("source_sha256") != PHASE85_SOURCE_SHA256):
        raise ValueError("Pilot is not in the approved revalidation state")
    prefix = f"{job['user_id']}/{job_id}/internal"
    archive = f"{prefix}/revisions/phase85a-{run_id}-{attempt}"
    audit_rows = {}
    for table in ("corrections", "exceptions", "job_events"):
        audit_rows[table] = db._request_json("GET", f"/rest/v1/{table}?job_id=eq.{job_id}&select=*")
    if audit_rows["corrections"]:
        raise ValueError("Teacher corrections exist; this zero-correction replay is ineligible")
    original = {}
    for name in ("ingestion.json", "normalized.json", "structure.json", "semantic.json", "canonical.json",
                 "validation.json", "visual/evidence.json", "visual/evidence.checkpoint.json"):
        original[name] = db.download_object(BUCKET, f"{prefix}/{name}")
    visual = json.loads(original["visual/evidence.json"])
    if visual.get("job_id") != job_id:
        raise ValueError("Checkpoint job identity differs")
    if visual.get("coordinate_revalidation") is not None:
        raise ValueError("This one-time pilot revalidation already completed its visual replay")
    source_bytes = db.download_object(BUCKET, validate_source_path(job))
    if len(source_bytes) != 1_007_519 or hashlib.sha256(source_bytes).hexdigest() != PHASE85_SOURCE_SHA256:
        raise ValueError("Immutable pilot source differs")
    normalized = json.loads(original["normalized.json"])
    if normalized.get("source", {}).get("sha256") != PHASE85_SOURCE_SHA256:
        raise ValueError("Saved normalization source differs")
    free_regions = {r["region_id"] for r in visual["runs"] if r.get("provider") in {"groq", "cloudflare"}}
    if free_regions != PHASE85_SAVED_REGIONS:
        raise ValueError("The original six approved free-provider checkpoints differ")
    rebuilt = rebuild_visual_checkpoint(visual, source_bytes, normalized)
    if rebuilt["coordinate_revalidation"]["recovered_openai_regions"] != 15 or len(rebuilt["runs"]) != 21:
        raise ValueError("Expected fifteen Luna and six compatible saved regions")
    # Verify stored original crops too; replay does not replace any source crop.
    for asset in visual["assets"]:
        crop = db.download_object(BUCKET, f"{job['user_id']}/{job_id}/{asset['path']}")
        if hashlib.sha256(crop).hexdigest() != asset["sha256"]:
            raise ValueError("Stored original crop differs")
    for name, data in original.items():
        db.upload_object(BUCKET, f"{archive}/{name}", data, content_type="application/json", upsert=False)
    db.upload_json(BUCKET, f"{archive}/audit.json", {"job": job, **audit_rows,
                   "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}}, upsert=False)
    # Compare status, stage and revision time: do not appropriate a concurrently edited job.
    updated = urllib.parse.quote(job["updated_at"], safe="")
    claimed = db._request_json("PATCH", f"/rest/v1/jobs?id=eq.{job_id}&status=eq.needs_review"
                              f"&stage=eq.phase5_canonicalized&updated_at=eq.{updated}",
                              body={"status": "dispatched", "stage": "coordinate_revalidation",
                                    "attempt_count": int(job.get("attempt_count") or 0) + 1,
                                    "dispatched_at": utc_now(), "updated_at": utc_now()}, prefer="return=representation")
    if not isinstance(claimed, list) or len(claimed) != 1:
        raise ValueError("Pilot revision changed before revalidation claim")
    db.add_event(claimed[0], "coordinate_revalidation_started", "coordinate_revalidation", {
        "archive_path": archive, "contract": OPENAI_COORDINATE_CONTRACT,
        "github_run_id": run_id, "github_actor": os.environ.get("GITHUB_ACTOR"),
        "source_sha256": PHASE85_SOURCE_SHA256, "visual_inference_calls": 0,
    })
    if db._request_json("GET", f"/rest/v1/corrections?job_id=eq.{job_id}&select=id"):
        db.patch_job(job_id, "dispatched", {"status": job["status"], "stage": job["stage"],
                                           "updated_at": utc_now()})
        db.add_event(job, "coordinate_revalidation_aborted", "coordinate_revalidation",
                     {"reason": "concurrent_teacher_correction", "archive_path": archive})
        raise ValueError("Teacher correction arrived during revalidation claim")
    # Ordinary worker lifecycle publishes a replacement exception generation;
    # archived originals and prior exception/event rows remain available.
    outcome = run_job(job_id, replay_visual=rebuilt, db=db)
    final = db.get_job(job_id)
    db.add_event(final, "coordinate_revalidation_complete", "coordinate_revalidation", {
        "archive_path": archive, "contract": OPENAI_COORDINATE_CONTRACT,
        "status": final["status"], "stage": final["stage"], "visual_inference_calls": 0,
    })
    return outcome


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m engine.src.memo_engine.coordinate_revalidation <pilot_job_id>")
    raise SystemExit(revalidate_job(sys.argv[1]))
