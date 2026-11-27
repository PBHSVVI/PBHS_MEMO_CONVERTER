"""Distinct owner-authorised Phase 8.5B lifecycle; never bypass Phase 8.5A's guard."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import urllib.parse
from collections import Counter

from .http import SupabaseRest
from .openai_adapter import OpenAIInterpreter
from .openai_credit import CreditLedger, MODEL, PBHS_URL, PILOT_JOB, reconcile_ledger
from .provider_fabric import ProviderTaskRequest, default_provider_registry
from .visual_evidence import _render_regions, _vision_schema, validate_visual_response, visual_system_prompt, ensure_visual_evidence_ids

# Owner-specified comparison targets identify crops, never expected answers.
TARGETS = (
    ("page-0001-q1_2.png", "solution-role misclassification"),
    ("page-0002-q2_1_2.png", "ambiguous fraction grouping"),
    ("page-0003-q4_2.png", "unreliable fraction transcription"),
    ("page-0004-q5_1.png", "uncertain diagram digit"),
    ("page-0004-q5_2_1.png", "uncertain decimal transcription"),
    ("page-0005-q4_1.png", "incomplete multiplication transcription"),
)
VERSION="marking-revalidation-v1"


def refresh_readings(visual: dict, source: bytes, normalized: dict, interpreter: OpenAIInterpreter,
                     *, cached: dict | None = None, checkpoint=None, crop_store=None) -> dict:
    regions={r["asset_path"]:r for r in _render_regions(source,normalized)}
    assets={a["path"]:a for a in visual["assets"]}
    for run in visual["runs"]:
        ref=run["region_id"]
        if hashlib.sha256(regions[ref]["image_bytes"]).hexdigest()!=run["crop_digest"] or assets[ref]["sha256"]!=run["crop_digest"]:
            raise ValueError("Original source crop changed before targeted reinterpretation")
    tasks=[]
    for name,reason in TARGETS:
        original="internal/visual/regions/"+name
        region=copy.deepcopy(regions[original]);region["asset_path"]="internal/visual/reinterpretations/phase85b-"+name
        tasks.append((region,[original],reason))
    # The existing lower-family crop contains both labelled working lines. Keep
    # original bytes; an explicit two-question scope prevents cross-family use.
    original="internal/visual/regions/page-0005-q4_2_2.png"
    family=copy.deepcopy(regions[original]);family.update({
        "asset_path":"internal/visual/reinterpretations/phase85b-page-0005-family4_2.png",
        "question_refs":["4.2.1","4.2.2"],"owned_bbox":family["render_bbox"],
        "association_scope":"labelled_question_family",
    })
    tasks.append((family,["internal/visual/regions/page-0005-q4_2_1.png",original],"working lies below adjacent printed prompts"))
    checkpoint_record={"version":VERSION,"source_sha256":visual["source_sha256"],"responses":[]}
    reusable={r["asset_path"]:r for r in (cached or {}).get("responses",[]) if (cached or {}).get("version")==VERSION and (cached or {}).get("source_sha256")==visual["source_sha256"]}
    result=copy.deepcopy(visual);history=[];new_calls=0
    for region,original_refs,reason in tasks:
        ref=region["asset_path"];digest=hashlib.sha256(region["image_bytes"]).hexdigest()
        saved=reusable.get(ref)
        if saved and saved["crop_digest"]!=digest:raise ValueError("Recognition checkpoint crop differs")
        if not saved:
            request=ProviderTaskRequest(task_type="visual_interpretation",region_id=ref,
                current_question_owner=region["question_refs"][0] if len(region["question_refs"])==1 else None,
                source_question=region["question_refs"][0],source_page=region["page"],
                source_digest=visual["source_sha256"],crop_digest=digest,crop_bytes=region["image_bytes"],
                crop_mime_type=region["mime_type"],interpretation_schema_version="1.0",task_prompt_version=VERSION,
                privacy_classification="school_private",prompt=visual_system_prompt()+
                "\nTranscribe exactly as written, even when mathematically wrong. Do not repair arithmetic or invent a missing answer. "
                "Read complete fractions, every factor and every visible decimal digit. Distinguish blue working from red marking instructions. "
                "Use only these source question labels: "+json.dumps(region["question_refs"]),response_schema=_vision_schema(region["page"]))
            response=interpreter.visual(request,default_provider_registry()["openai"],None,1,__import__('time').monotonic)
            saved={"asset_path":ref,"crop_digest":digest,"payload":response.normalized_result,
                   "result_digest":response.result_digest,"usage":response.usage,"quota":response.quota,"latency_ms":response.latency_ms}
            new_calls+=1
        validated=validate_visual_response({**saved["payload"],"provider":"openai","model":MODEL},region)
        checkpoint_record["responses"].append(saved)
        if checkpoint:checkpoint(checkpoint_record)
        old=[e for e in result["evidence"] if e["rendered_asset_ref"] in original_refs]
        history.append({"original_refs":original_refs,"reason":reason,"original_observations":old,
                        "new_asset_ref":ref,"result_digest":saved["result_digest"]})
        result["evidence"]=[e for e in result["evidence"] if e["rendered_asset_ref"] not in original_refs]+validated["evidence"]
        result["mark_changes"]=[e for e in result["mark_changes"] if e["rendered_asset_ref"] not in original_refs]+validated["mark_changes"]
        ensure_visual_evidence_ids(result["evidence"]);ensure_visual_evidence_ids(result["mark_changes"])
        asset={k:region[k] for k in ["pixel_width","pixel_height","page","question_refs","render_bbox","owned_bbox","page_bbox"]}
        result["assets"].append({**asset,"path":ref,"sha256":digest,"size_bytes":len(region["image_bytes"]),
                                 "mime_type":region["mime_type"],"preservation_method":"source_crop"})
        result.setdefault("coordinate_responses",[]).append({"region_id":ref,"crop_digest":digest,
                                                            "provenance":validated["coordinate_provenance"]})
        if crop_store:crop_store(ref,region["image_bytes"],region["mime_type"])
    result["recognition_revisions"]=history
    result["marking_revalidation"]={"version":VERSION,"new_visual_calls":new_calls,
        "targeted_requests":len(tasks),"affected_original_regions":sum(len(t[1]) for t in tasks),
        "original_region_coverage":21,"prior_coordinate_contract":visual["coordinate_revalidation"]["contract"]}
    result["summary"].update({"vision_calls":0,"effective_evidence_count":sum(e.get("effective",True) for e in result["evidence"]),
                               "suppressed_evidence_count":sum(not e.get("effective",True) for e in result["evidence"])})
    return result


def _verify_prepared_review(prior: dict, current: dict, old_math: dict, new_math: dict,
                            old_exceptions: list[dict], new_exceptions: list[dict]) -> dict:
    if any(prior[key] != current[key] for key in ("source", "questions", "totals", "status")) or old_math != new_math:
        raise ValueError("Review preparation altered source, canonical working, admitted marks or mathematics")

    def review_rows(items):
        return Counter(
            json.dumps([row["category"], row["level"], row.get("affected_id"), row["message"],
                        row.get("suggestions", [])], sort_keys=True)
            for row in items if row.get("status", "open") == "open"
        )

    before, after = review_rows(old_exceptions), review_rows(new_exceptions)
    removed = list((before - after).elements())
    if (after - before or len(removed) != 3
            or any(json.loads(row)[0] != "visual_evidence_association_uncertain" for row in removed)):
        raise ValueError("Review preparation must only omit the three redundant context association cards")
    return {"open_before": before.total(), "open_after": after.total(), "admitted_working_preserved": True}


def preview_admission(job: dict, source: bytes, originals: dict[str, bytes], *,
                      reference_results: list[dict] | None = None,
                      review_exceptions: list[dict] | None = None) -> dict:
    """Validate the full saved canonical replay before claiming the live job."""
    from .canonical import build_canonical_memo
    from .guideline_verification import verify_guideline, require_complete_admission_cache
    from .marking_interpretation import interpret_marking
    from .phase7_5 import enrich_structure_phase7_5
    from .semantic import build_semantic_plan, interpret_semantics
    from .structure import extract_structure
    from .visual_evidence import fuse_visual_evidence

    def saved(name):
        return json.loads(originals[name])

    normalized = saved("normalized.json")
    visual = saved("visual/evidence.json")
    marking = saved("marking_interpretation.json")
    cached_verification = saved("guideline_verification.json")
    structure = fuse_visual_evidence(enrich_structure_phase7_5(extract_structure(normalized), normalized), visual)
    structure, _ = interpret_marking(structure, normalized, visual, cached=marking)

    def unavailable(_):
        raise ValueError("Admission replay unexpectedly requested source crop I/O")

    verification = verify_guideline(structure, normalized, visual, load_crop=unavailable,
                                   verifier=None, cached=cached_verification)
    require_complete_admission_cache(cached_verification, verification)
    reference = {}
    if reference_results is not None:
        from .reference_replay import apply_reference_results
        reference = apply_reference_results(structure, reference_results)
    if build_semantic_plan(structure)[1]:
        raise ValueError("Admission preview would require fresh semantic interpretation")
    semantic = interpret_semantics(structure)
    canonical, validation, canonical_exceptions = build_canonical_memo(
        job, saved("ingestion.json"), normalized, structure, semantic, source,
    )
    prior, old_math = saved("canonical.json"), saved("validation.json")["mathematical_consistency"]
    new_math = validation["mathematical_consistency"]
    prior_total = prior["totals"]["computed"]
    conflicts = new_math["conflict_count"]
    prepared = {}
    if review_exceptions is not None:
        prepared = _verify_prepared_review(prior, canonical, old_math, new_math, review_exceptions,
                                           structure["exceptions"] + semantic["exceptions"] + canonical_exceptions)
    elif canonical["totals"]["computed"] <= prior_total or conflicts > old_math["conflict_count"]:
        raise ValueError("Saved admission replay did not improve the canonical result safely")
    return {"computed_before": prior_total, "computed_after": canonical["totals"]["computed"],
            "canonical_status": canonical["status"], "math_conflicts": conflicts,
            **verification["summary"], **prepared,
            **({"reference": reference} if reference_results is not None else {})}


def revalidate_marking(job_id: str, db=None, *, guideline: bool = False, admission: bool = False,
                       reference: bool = False, prepare_review: bool = False) -> int:
    from .cli import BUCKET, PHASE85_SOURCE_SHA256, run_job, utc_now
    from .ingestion import validate_source_path
    if job_id!=PILOT_JOB:raise ValueError("Only the authorised marking pilot is eligible")
    db=db or SupabaseRest()
    if db.base!=PBHS_URL:raise ValueError("Wrong project")
    if (os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("GITHUB_REPOSITORY")!="PBHSVVI/PBHS_MEMO_CONVERTER"
        or os.environ.get("GITHUB_REF")!="refs/heads/main" or os.environ.get("GITHUB_WORKFLOW")!="Process Memo"):
        raise ValueError("Authorised hosted Process Memo execution required")
    run_id=os.environ["GITHUB_RUN_ID"];attempt=os.environ["GITHUB_RUN_ATTEMPT"]
    if not run_id.isdigit() or not attempt.isdigit():raise ValueError("Invalid hosted audit identity")
    job=db.get_job(job_id)
    if job["status"]!="needs_review" or job["stage"]!="phase5_canonicalized" or job.get("source_sha256")!=PHASE85_SOURCE_SHA256:
        raise ValueError("Pilot marking revalidation state differs")
    prefix=f"{job['user_id']}/{job_id}/internal"
    if prepare_review:
        revision, operation, version = "phase86a", "review_preparation", "review-preparation-v1"
    elif reference:
        revision, operation, version = "phase85e", "reference_revalidation", "reference-revalidation-v1"
    elif admission:
        revision, operation, version = "phase85d", "admission_revalidation", "admission-revalidation-v1"
    elif guideline:
        revision, operation, version = "phase85c", "guideline_revalidation", "guideline-revalidation-v1"
    else:
        revision, operation, version = "phase85b", "marking_revalidation", VERSION
    archive=f"{prefix}/revisions/{revision}-{run_id}-{attempt}"
    rows={table:db._request_json("GET",f"/rest/v1/{table}?job_id=eq.{job_id}&select=*") for table in ["corrections","exceptions","job_events"]}
    if rows["corrections"]:raise ValueError("Teacher corrections require a different lifecycle")
    names = [
        "ingestion.json","normalized.json","structure.json","semantic.json","canonical.json","validation.json",
        "visual/evidence.json","visual/evidence.checkpoint.json"]
    cached_only = admission or reference or prepare_review
    if guideline or cached_only:
        names += ["marking_interpretation.json", "recognition_revalidation.json"]
    if cached_only:
        names += ["guideline_verification.json"]
    originals={name:db.download_object(BUCKET,f"{prefix}/{name}") for name in names}
    visual=json.loads(originals["visual/evidence.json"])
    if not visual.get("coordinate_revalidation") or visual.get("job_id")!=job_id:
        raise ValueError("Accepted coordinate revalidation history is required")
    if prepare_review:
        previous = visual.get("reference_revalidation") or {}
        if (job.get("attempt_count") != 9 or previous.get("version") != "reference-revalidation-v1"
                or previous.get("github_run_id") != "45984780116"):
            raise ValueError("The authorised Phase 8.5E review generation is required")
        before_ledger = reconcile_ledger(db)
        print("Review preparation credit before " + json.dumps(before_ledger, sort_keys=True))
    elif reference:
        if (job.get("attempt_count") != 8 or visual.get("reference_revalidation") or
                visual.get("admission_revalidation", {}).get("version") != "admission-revalidation-v1"):
            raise ValueError("An unrevised Phase 8.5D admission generation is required")
        before_ledger = reconcile_ledger(db)
        print("Reference credit before " + json.dumps(before_ledger, sort_keys=True))
    elif admission:
        if (visual.get("guideline_revalidation", {}).get("version") != "guideline-revalidation-v1"
                or not visual.get("marking_revalidation") or visual.get("admission_revalidation")):
            raise ValueError("An unrevised Phase 8.5C guideline generation is required")
        before_ledger = reconcile_ledger(db)
        print("Admission credit before " + json.dumps(before_ledger, sort_keys=True))
    elif guideline:
        if not visual.get("marking_revalidation") or visual.get("guideline_revalidation"):
            raise ValueError("An unrevised Phase 8.5B marking generation is required")
        before_ledger = reconcile_ledger(db)
        if before_ledger["available_worker_slots"] < 30:
            raise ValueError("Insufficient included-credit slots for controlled guideline verification")
        print("Guideline credit before " + json.dumps(before_ledger, sort_keys=True))
    elif visual.get("marking_revalidation"):
        raise ValueError("Marking revalidation already published")
    source=db.download_object(BUCKET,validate_source_path(job))
    if hashlib.sha256(source).hexdigest()!=PHASE85_SOURCE_SHA256 or len(source)!=1_007_519:raise ValueError("Immutable source differs")
    if reference or prepare_review:
        from .reference_replay import TRIAL_RUN, load_trial
        preview = preview_admission(
            job, source, originals, reference_results=load_trial(db, job, source),
            review_exceptions=rows["exceptions"] if prepare_review else None,
        )
        print("Reference read-only preview " + json.dumps(preview, sort_keys=True))
    elif admission:
        print("Admission read-only preview " + json.dumps(preview_admission(job, source, originals), sort_keys=True))
    for name,data in originals.items():db.upload_object(BUCKET,f"{archive}/{name}",data,content_type="application/json",upsert=False)
    db.upload_json(BUCKET,f"{archive}/audit.json",{"job":job,**rows,"sha256":{n:hashlib.sha256(d).hexdigest() for n,d in originals.items()}},upsert=False)
    query=f"/rest/v1/jobs?id=eq.{job_id}&status=eq.needs_review&stage=eq.phase5_canonicalized&updated_at=eq.{urllib.parse.quote(job['updated_at'],safe='')}"
    claimed=db._request_json("PATCH",query,body={"status":"dispatched","stage":operation,
        "attempt_count":int(job.get("attempt_count") or 0)+1,"updated_at":utc_now(),"dispatched_at":utc_now()},prefer="return=representation")
    if not claimed or len(claimed)!=1:raise ValueError("Concurrent pilot revision changed")
    db.add_event(claimed[0],operation + "_started",operation,{
        "archive_path":archive,"github_run_id":run_id,"actor":os.environ.get("GITHUB_ACTOR"),"version":version})
    try:
        if db._request_json("GET",f"/rest/v1/corrections?job_id=eq.{job_id}&select=id"):raise ValueError("Concurrent teacher correction")
        if prepare_review:
            rebuilt = visual
        elif reference:
            rebuilt = {**visual, "reference_revalidation": {"version": version, "github_run_id": run_id,
                                                           "trial_run_id": TRIAL_RUN}}
        elif admission:
            rebuilt = {**visual, "admission_revalidation": {"version": version, "github_run_id": run_id}}
        elif guideline:
            rebuilt = {**visual, "guideline_revalidation": {"version": version, "github_run_id": run_id}}
        else:
            checkpoint_path=f"{prefix}/recognition_revalidation.json"
            try:cached=db.download_json(BUCKET,checkpoint_path)
            except Exception:cached=None
            interpreter=OpenAIInterpreter(CreditLedger(db),os.environ,job_id=job_id)
            rebuilt=refresh_readings(visual,source,json.loads(originals["normalized.json"]),interpreter,cached=cached,
                checkpoint=lambda r:db.upload_json(BUCKET,checkpoint_path,r),
                crop_store=lambda ref,data,mime:db.upload_object(BUCKET,f"{job['user_id']}/{job_id}/{ref}",data,content_type=mime))
        outcome=run_job(job_id,replay_visual=rebuilt,db=db, **({"admission_replay": True} if cached_only else {}))
    except Exception as error:
        current=db.get_job(job_id)
        if current["status"]=="dispatched":
            db.patch_job(job_id,"dispatched",{"status":"needs_review","stage":"phase5_canonicalized","updated_at":utc_now()})
        db.add_event(current,operation + "_failed",operation,{"archive_path":archive,"error_type":type(error).__name__})
        raise
    final=db.get_job(job_id)
    prepared = {}
    if prepare_review:
        if final["status"] != "needs_review" or final["stage"] != "phase5_canonicalized":
            raise ValueError("Review preparation did not return to teacher review")
        live_exceptions = db._request_json("GET", f"/rest/v1/exceptions?job_id=eq.{job_id}&status=eq.open&select=*")
        prepared = _verify_prepared_review(
            json.loads(originals["canonical.json"]), db.download_json(BUCKET, f"{prefix}/canonical.json"),
            json.loads(originals["validation.json"])["mathematical_consistency"],
            db.download_json(BUCKET, f"{prefix}/validation.json")["mathematical_consistency"],
            rows["exceptions"], live_exceptions,
        )
        if db._request_json("GET", f"/rest/v1/corrections?job_id=eq.{job_id}&select=id"):
            raise ValueError("Concurrent teacher correction during review preparation")
        print("Review preparation result " + json.dumps(prepared, sort_keys=True))
    if cached_only:
        after_ledger = reconcile_ledger(db)
        label = "Review preparation" if prepare_review else "Reference" if reference else "Admission"
        print(label + " credit after " + json.dumps(after_ledger, sort_keys=True))
        if after_ledger != before_ledger:
            raise ValueError("Credit ledger changed during zero-inference admission replay")
    elif guideline:
        print("Guideline credit after " + json.dumps(reconcile_ledger(db), sort_keys=True))
    db.add_event(final,operation + "_complete",operation,{
        "archive_path":archive,"version":version,"status":final["status"],"stage":final["stage"], **prepared})
    return outcome


if __name__=="__main__":
    if len(sys.argv) not in {2, 3} or len(sys.argv) == 3 and sys.argv[2] not in {
        "--verify-guideline", "--replay-admission", "--replay-reference", "--prepare-review",
    }:
        raise SystemExit("Expected the authorised pilot job ID")
    option = sys.argv[2] if len(sys.argv) == 3 else None
    raise SystemExit(revalidate_marking(sys.argv[1], guideline=option == "--verify-guideline",
                                       admission=option == "--replay-admission", reference=option == "--replay-reference",
                                       prepare_review=option == "--prepare-review"))
