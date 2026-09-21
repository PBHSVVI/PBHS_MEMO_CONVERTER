from __future__ import annotations

import copy
import re
from typing import Any

from .structure import (
    effective_mark_total,
    flatten_units,
    parse_mark_points,
    printed_allocations,
    qtuple,
)

QUESTION_ID_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}$")


def _issue(category: str, affected_id: str | None, message: str, level: str = "red") -> dict[str, Any]:
    return {
        "level": level,
        "category": category,
        "affected_id": affected_id,
        "message": message,
        "suggestions": [],
    }


def _refresh_summary(structure: dict[str, Any]) -> None:
    exceptions = structure.get("exceptions") or []
    questions = structure.get("questions") or []
    summary = dict(structure.get("summary") or {})
    summary["detected_identifier_count"] = len(questions)
    summary["leaf_question_count"] = sum(1 for q in questions if not q.get("context_only"))
    summary["unique_question_count"] = len({str(q.get("question_id")) for q in questions})
    summary["amber_count"] = sum(1 for e in exceptions if e.get("level") == "amber")
    summary["red_count"] = sum(1 for e in exceptions if e.get("level") == "red")
    summary["review_required"] = bool(exceptions)
    structure["summary"] = summary


def _remove_exception(structure: dict[str, Any], category: str, affected_id: str | None) -> None:
    structure["exceptions"] = [
        item for item in structure.get("exceptions", [])
        if not (str(item.get("category")) == category and item.get("affected_id") == affected_id)
    ]


def _promote_unlabeled_question(
    structure: dict[str, Any],
    normalized: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    target_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not QUESTION_ID_RE.fullmatch(target_id):
        return None, _issue("correction_target_invalid", affected_id, f"Confirmed correction {correction_id} has an invalid question identifier.")
    if any(str(q.get("question_id")) == target_id for q in structure.get("questions", [])):
        return None, _issue("correction_target_conflict", target_id, f"Question {target_id} already exists.")

    candidates = [x for x in structure.get("unlabeled_mark_blocks", []) if str(x.get("candidate") or "") == target_id]
    if len(candidates) != 1:
        return None, _issue("correction_evidence_unresolved", affected_id, f"Confirmed correction {correction_id} could not resolve exactly one unlabelled source row for {target_id}.")

    entry = candidates[0]
    block_index = int(entry.get("block_index", -1))
    blocks = flatten_units(normalized)
    if not 0 <= block_index < len(blocks):
        return None, _issue("correction_evidence_unresolved", target_id, f"Source evidence for confirmed correction {correction_id} is unavailable.")

    block = blocks[block_index]
    allocations = printed_allocations(block.get("allocation", ""))
    if len(allocations) != 1:
        return None, _issue("correction_allocation_ambiguous", target_id, f"Confirmed correction {correction_id} does not resolve to one printed allocation.")

    points = parse_mark_points(block.get("marking", ""))
    computed, calc_mode = effective_mark_total(points, block.get("marking", ""))
    path = list(qtuple(target_id))
    question = {
        "question_id": target_id,
        "path": path,
        "depth": len(path),
        "context_only": False,
        "source_block_index": block_index,
        "printed_marks": int(allocations[0]),
        "computed_shorthand_marks": computed if computed else None,
        "mark_calculation_mode": calc_mode,
        "mark_points": points,
        "source_preview": str(block.get("source") or "")[:240],
        "correction_overlay": {"correction_id": correction_id, "operation": "promote_unlabeled_question"},
    }
    structure.setdefault("questions", []).append(question)
    structure["questions"].sort(key=lambda q: (int(q.get("source_block_index", 10**9)), tuple(q.get("path") or (999,))))
    structure["unlabeled_mark_blocks"] = [x for x in structure.get("unlabeled_mark_blocks", []) if x is not entry]
    _remove_exception(structure, category, affected_id)
    return {
        "correction_id": correction_id,
        "operation": "promote_unlabeled_question",
        "category": category,
        "affected_id": affected_id,
        "target_id": target_id,
        "source_block_index": block_index,
    }, None


def _rename_question_identifier(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    target_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    source_id = str(affected_id or "")
    if not QUESTION_ID_RE.fullmatch(source_id) or not QUESTION_ID_RE.fullmatch(target_id):
        return None, _issue("correction_target_invalid", affected_id, f"Confirmed correction {correction_id} contains an invalid numbering patch.")
    matches = [q for q in structure.get("questions", []) if str(q.get("question_id")) == source_id]
    if len(matches) != 1:
        return None, _issue("correction_evidence_unresolved", source_id, f"Confirmed correction {correction_id} could not resolve exactly one question {source_id}.")
    if any(str(q.get("question_id")) == target_id for q in structure.get("questions", []) if q is not matches[0]):
        return None, _issue("correction_target_conflict", target_id, f"Question identifier {target_id} already exists.")

    q = matches[0]
    q["question_id"] = target_id
    q["path"] = list(qtuple(target_id))
    q["depth"] = len(q["path"])
    q["correction_overlay"] = {"correction_id": correction_id, "operation": "rename_question_identifier", "source_id": source_id}
    structure["questions"].sort(key=lambda item: (int(item.get("source_block_index", 10**9)), tuple(item.get("path") or (999,))))
    _remove_exception(structure, category, affected_id)
    return {
        "correction_id": correction_id,
        "operation": "rename_question_identifier",
        "category": category,
        "affected_id": source_id,
        "target_id": target_id,
        "source_block_index": q.get("source_block_index"),
    }, None


def apply_confirmed_corrections(
    structure: dict[str, Any],
    normalized: dict[str, Any],
    corrections: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply confirmed corrections as an immutable interpretation overlay."""
    result = copy.deepcopy(structure)
    applied: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for correction in corrections:
        if correction.get("confirmation_status") != "confirmed":
            continue
        correction_id = str(correction.get("id") or "")
        patch = correction.get("proposed_patch")
        if not isinstance(patch, dict):
            issues.append(_issue("correction_patch_missing", None, f"Confirmed correction {correction_id} has no structured patch."))
            continue

        category = str(patch.get("category") or "")
        affected_id = patch.get("affected_id")
        operation = str(patch.get("operation") or "")
        suggestion = patch.get("suggestion")
        target_id = None
        if isinstance(suggestion, dict) and isinstance(suggestion.get("candidate"), str):
            target_id = suggestion["candidate"].strip()
        elif isinstance(patch.get("target_id"), str):
            target_id = str(patch["target_id"]).strip()

        applied_item = None
        issue = None
        if category == "unlabeled_mark_bearing_question" and operation in {"accept_suggestion", "promote_unlabeled_question"} and target_id:
            applied_item, issue = _promote_unlabeled_question(
                result, normalized, correction_id=correction_id, category=category,
                affected_id=affected_id, target_id=target_id,
            )
        elif category in {"numbering_jump", "suspicious_question_identifier"} and operation in {"accept_suggestion", "rename_question_identifier"} and target_id:
            applied_item, issue = _rename_question_identifier(
                result, correction_id=correction_id, category=category,
                affected_id=affected_id, target_id=target_id,
            )
        else:
            issue = _issue(
                "correction_application_unsupported",
                str(affected_id) if affected_id is not None else None,
                f"Confirmed correction {correction_id} cannot yet be applied deterministically; further reinterpretation is required.",
            )

        if applied_item:
            applied.append(applied_item)
        if issue:
            issues.append(issue)

    result.setdefault("exceptions", []).extend(issues)
    result["correction_overlay"] = {
        "confirmed_count": sum(1 for c in corrections if c.get("confirmation_status") == "confirmed"),
        "applied_count": len(applied),
        "issue_count": len(issues),
        "applied": applied,
    }
    _refresh_summary(result)
    return result, applied, issues
