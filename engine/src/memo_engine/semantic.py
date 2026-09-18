from __future__ import annotations

import os
import time
from typing import Any

from .ai_router import ProviderError, ProviderRun, classify


ALLOWED_BY_CODE: dict[str, set[str]] = {
    "M": {"method"},
    "CA": {"consistent_accuracy"},
    "R": {"reason"},
    "A": {"accuracy", "answer"},
    "F": {"formula", "factorisation"},
    "S": {"statement", "substitution", "simplification"},
}


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def deterministic_semantic(point: dict[str, Any]) -> tuple[str | None, str | None]:
    code = (point.get("code") or "").upper()
    desc = _norm(point.get("descriptor"))
    existing = point.get("semantic")

    if code == "M":
        return "method", "shorthand_M"
    if code == "CA":
        return "consistent_accuracy", "shorthand_CA"
    if code == "R":
        return "reason", "shorthand_R"

    if code == "F":
        if "formula" in desc:
            return "formula", "descriptor_formula"
        if "fac" in desc or "factor" in desc:
            return "factorisation", "descriptor_factorisation"
        return None, None

    if code == "A":
        if any(token in desc for token in ["answer", "answers", " ans", "final answer"]):
            return "answer", "descriptor_answer"
        return None, None

    if code == "S":
        return None, None

    # Tick notation or un-coded source: use only explicit descriptor semantics.
    if not code:
        if any(token in desc for token in ["answer", "answers"]):
            return "answer", "descriptor_answer"
        if "formula" in desc:
            return "formula", "descriptor_formula"
        if "factor" in desc or desc == "factors":
            return "factorisation", "descriptor_factorisation"
        if "substitution" in desc:
            return "substitution", "descriptor_substitution"
        if "simplif" in desc:
            return "simplification", "descriptor_simplification"
        if "reason" in desc:
            return "reason", "descriptor_reason"
        if "conclusion" in desc:
            return "conclusion", "descriptor_conclusion"
        if any(token in desc for token in ["shape", "intercept", "asymptote"]):
            return "graph_feature", "descriptor_graph_feature"
        if "construction" in desc:
            return "construction", "descriptor_construction"
        if desc == "given":
            return "given", "descriptor_given"
        if "selection" in desc:
            return "selection", "descriptor_selection"
        if "progressive" in desc or "progression" in desc:
            return "progressive", "descriptor_progressive"

        if existing and existing not in {
            "other",
            "formula_or_factorisation",
            "statement_or_substitution_or_simplification",
        }:
            return existing, "phase3_descriptor_rule"

    return None, None


def _candidate_id(question_id: str, mark_index: int) -> str:
    safe_q = question_id.replace(".", "_")
    return f"{safe_q}__m{mark_index + 1}"


def build_semantic_plan(structure: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for question in structure.get("questions", []):
        qid = question["question_id"]
        points = question.get("mark_points") or []
        for mark_index, point in enumerate(points):
            cid = _candidate_id(qid, mark_index)
            semantic, rule = deterministic_semantic(point)

            base = {
                "candidate_id": cid,
                "question_id": qid,
                "mark_index": mark_index,
                "count": point.get("count"),
                "source_shorthand": point.get("code"),
                "descriptor": point.get("descriptor") or "",
                "source_notation": point.get("notation"),
            }

            if semantic is not None:
                resolved.append({
                    **base,
                    "semantic_type": semantic,
                    "confidence_score": 1.0,
                    "band": "green",
                    "rationale": f"Deterministic rule: {rule}.",
                    "resolution_method": "deterministic",
                })
                continue

            neighbours = []
            for neighbor_index in range(max(0, mark_index - 1), min(len(points), mark_index + 2)):
                if neighbor_index == mark_index:
                    continue
                neighbor = points[neighbor_index]
                neighbours.append({
                    "index": neighbor_index,
                    "code": neighbor.get("code"),
                    "descriptor": neighbor.get("descriptor") or "",
                })

            candidates.append({
                **base,
                "question_context": (question.get("source_preview") or "")[:360],
                "neighboring_marks": neighbours,
            })

    return resolved, candidates


def _validate_result(
    candidate: dict[str, Any],
    result: dict[str, Any],
) -> tuple[bool, str | None]:
    if result.get("candidate_id") != candidate["candidate_id"]:
        return False, "candidate_id_mismatch"

    semantic = result.get("semantic_type")
    code = (candidate.get("source_shorthand") or "").upper()
    allowed = ALLOWED_BY_CODE.get(code)
    if allowed is not None and semantic not in allowed:
        return False, "shorthand_semantic_conflict"

    score = result.get("confidence_score")
    if not isinstance(score, (int, float)) or not 0 <= score <= 1:
        return False, "confidence_invalid"

    if result.get("band") not in {"green", "amber", "red"}:
        return False, "band_invalid"

    return True, None


def _unresolved_provider_result(
    candidate: dict[str, Any],
    exc: ProviderError,
) -> dict[str, Any]:
    return {
        **candidate,
        "semantic_type": "other",
        "confidence_score": 0.0,
        "band": "amber",
        "rationale": "Automated semantic classification could not be completed safely.",
        "provider_valid": False,
        "provider_validation_issue": "provider_failed",
        "provider_error_code": exc.code,
        "resolution_method": "provider_unresolved",
    }


def _run_batches(
    candidates: list[dict[str, Any]],
    *,
    strong: bool,
    batch_size: int,
) -> tuple[list[dict[str, Any]], list[ProviderRun]]:
    output: list[dict[str, Any]] = []
    runs: list[ProviderRun] = []

    starts = list(range(0, len(candidates), batch_size))
    min_interval = max(
        0.0,
        float(os.environ.get("MEMO_AI_MIN_INTERVAL_SECONDS", "15")),
    )

    for batch_number, start in enumerate(starts):
        if batch_number > 0 and min_interval:
            time.sleep(min_interval)

        batch = candidates[start:start + batch_size]

        try:
            run = classify(batch, strong=strong)
        except ProviderError as exc:
            if exc.code == "AI_PROVIDER_TOOL_USE_FAILED" and len(batch) > 1:
                for single_index, candidate in enumerate(batch):
                    if single_index > 0:
                        time.sleep(3.0)
                    try:
                        single_run = classify([candidate], strong=strong)
                        runs.append(single_run)
                        result = single_run.results[0]
                        valid, issue = _validate_result(candidate, result)
                        output.append({
                            **candidate,
                            **result,
                            "provider_valid": valid,
                            "provider_validation_issue": issue,
                            "resolution_method": f"{single_run.provider}:{single_run.model}",
                        })
                    except ProviderError as single_exc:
                        if single_exc.retryable:
                            output.append(_unresolved_provider_result(candidate, single_exc))
                        else:
                            raise
                continue

            if exc.retryable:
                for candidate in batch:
                    output.append(_unresolved_provider_result(candidate, exc))
                continue
            raise

        runs.append(run)

        by_id = {item.get("candidate_id"): item for item in run.results}
        if len(by_id) != len(batch):
            exc = ProviderError(
                "AI_PROVIDER_RESULT_COUNT_MISMATCH",
                "The AI provider did not return exactly one result per semantic candidate.",
                retryable=True,
            )
            for candidate in batch:
                output.append(_unresolved_provider_result(candidate, exc))
            continue

        for candidate in batch:
            result = by_id.get(candidate["candidate_id"])
            if result is None:
                output.append(
                    _unresolved_provider_result(
                        candidate,
                        ProviderError(
                            "AI_PROVIDER_RESULT_MISSING",
                            "The AI provider omitted a semantic candidate.",
                            retryable=True,
                        ),
                    )
                )
                continue
            valid, issue = _validate_result(candidate, result)
            output.append({
                **candidate,
                **result,
                "provider_valid": valid,
                "provider_validation_issue": issue,
                "resolution_method": f"{run.provider}:{run.model}",
            })

    return output, runs


def interpret_semantics(structure: dict[str, Any]) -> dict[str, Any]:
    deterministic, candidates = build_semantic_plan(structure)
    batch_size = max(1, min(20, int(os.environ.get("MEMO_AI_BATCH_SIZE", "16"))))

    fast_results: list[dict[str, Any]] = []
    runs: list[ProviderRun] = []

    if candidates:
        fast_results, fast_runs = _run_batches(
            candidates,
            strong=False,
            batch_size=batch_size,
        )
        runs.extend(fast_runs)

    escalation_candidates: list[dict[str, Any]] = []
    fast_by_id = {item["candidate_id"]: item for item in fast_results}

    for candidate in candidates:
        result = fast_by_id[candidate["candidate_id"]]
        if (
            not result["provider_valid"]
            or result["band"] != "green"
            or float(result["confidence_score"]) < 0.90
        ):
            escalation_candidates.append(candidate)

    strong_results: list[dict[str, Any]] = []
    enable_escalation = os.environ.get("MEMO_AI_ESCALATE", "true").strip().lower() not in {
        "0", "false", "no"
    }
    if escalation_candidates and enable_escalation:
        strong_results, strong_runs = _run_batches(
            escalation_candidates,
            strong=True,
            batch_size=batch_size,
        )
        runs.extend(strong_runs)

    strong_by_id = {item["candidate_id"]: item for item in strong_results}
    final_ai: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []

    for candidate in candidates:
        cid = candidate["candidate_id"]
        chosen = strong_by_id.get(cid) or fast_by_id[cid]

        is_green = (
            chosen["provider_valid"]
            and chosen["band"] == "green"
            and float(chosen["confidence_score"]) >= 0.90
        )

        final_band = (
            "green"
            if is_green
            else ("red" if chosen["band"] == "red" else "amber")
        )

        final_ai.append({
            "candidate_id": cid,
            "question_id": candidate["question_id"],
            "mark_index": candidate["mark_index"],
            "count": candidate["count"],
            "source_shorthand": candidate["source_shorthand"],
            "descriptor": candidate["descriptor"],
            "semantic_type": chosen["semantic_type"],
            "confidence_score": chosen["confidence_score"],
            "band": final_band,
            "rationale": chosen["rationale"],
            "resolution_method": chosen["resolution_method"],
            "provider_valid": chosen["provider_valid"],
            "provider_validation_issue": chosen["provider_validation_issue"],
        })

        if not is_green:
            level = "red" if chosen["band"] == "red" else "amber"
            issue = chosen["provider_validation_issue"]

            if issue == "provider_failed":
                category = "semantic_provider_unresolved"
                message = (
                    f"Automated mark-semantic classification for "
                    f"{candidate['question_id']} could not be completed safely; "
                    "teacher confirmation is required."
                )
                suggestions = []
            else:
                category = "ambiguous_mark_semantics"
                message = (
                    f"Mark semantics for {candidate['question_id']} require confirmation."
                    if not issue
                    else f"AI semantic interpretation for {candidate['question_id']} conflicts with deterministic shorthand constraints."
                )
                suggestions = [{
                    "candidate_id": cid,
                    "semantic_type": chosen["semantic_type"],
                    "confidence_score": chosen["confidence_score"],
                }]

            exceptions.append({
                "level": level,
                "category": category,
                "affected_id": candidate["question_id"],
                "message": message,
                "suggestions": suggestions,
            })

    run_records = [
        {
            "provider": run.provider,
            "model": run.model,
            "candidate_count": run.candidate_count,
            "prompt_tokens": run.prompt_tokens,
            "output_tokens": run.output_tokens,
            "total_tokens": run.total_tokens,
            "elapsed_ms": run.elapsed_ms,
        }
        for run in runs
    ]

    return {
        "schema_version": "1.0",
        "phase": "phase4_semantics",
        "job_id": structure["job_id"],
        "privacy_mode": os.environ.get(
            "MEMO_PRIVACY_MODE", "APPROVED_EXTERNAL_ONLY"
        ).strip().upper(),
        "deterministic_results": deterministic,
        "ai_results": final_ai,
        "interpreter_runs": run_records,
        "exceptions": exceptions,
        "summary": {
            "mark_points_total": len(deterministic) + len(candidates),
            "deterministic_count": len(deterministic),
            "ai_candidate_count": len(candidates),
            "ai_resolved_green_count": sum(1 for item in final_ai if item["band"] == "green"),
            "semantic_exception_count": len(exceptions),
            "interpreter_run_count": len(runs),
        },
    }
