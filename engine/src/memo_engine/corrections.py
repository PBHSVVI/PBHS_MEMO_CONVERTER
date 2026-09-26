from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any

from .structure import (
    effective_mark_total,
    flatten_units,
    parse_mark_points,
    printed_allocations,
    qtuple,
)
from .phase7_5 import apply_phase7_5_patch

QUESTION_ID_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}$")


def effective_correction_history(
    corrections: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive replay history without changing confirmed evidence or database rows.

    A complete marking replacement retires older schemes and item-total overrides
    on the exact same target. A total-only override retires only earlier total
    overrides: it still needs the current scheme to validate against. Source
    allocation, numbering and subtotal operations compose independently.
    """
    def order(entry: tuple[int, dict[str, Any]]) -> tuple[Any, ...]:
        index, correction = entry
        value = correction.get("confirmed_at")
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return (timestamp, str(correction.get("id") or ""), index)
        except ValueError:
            # Legacy callers without timestamps retain their supplied order.
            return (datetime.min.replace(tzinfo=timezone.utc), "", index)

    ordered = [c for _, c in sorted(
        ((i, c) for i, c in enumerate(corrections)
         if c.get("confirmation_status") == "confirmed"), key=order,
    )]
    newer: dict[tuple[str, str], str] = {}
    history: list[dict[str, Any]] = []
    effective: list[dict[str, Any]] = []
    for correction in reversed(ordered):
        patch = correction.get("proposed_patch")
        patch = patch if isinstance(patch, dict) else {}
        operation = patch.get("operation")
        category = patch.get("category")
        target = str(patch.get("affected_id") or "").strip()
        correction_id = str(correction.get("id") or "")
        domain = None
        if QUESTION_ID_RE.fullmatch(target) and correction_id:
            if operation == "replace_mark_points" and category in {
                "mark_arithmetic_mismatch", "item_total_mismatch",
                "correction_mark_total_invalid",
            }:
                domain = "mark_scheme"
            elif operation == "set_item_total_override" and category == "item_total_mismatch":
                domain = "item_total"
        successor = newer.get((target, domain)) if domain else None
        history.append({
            "correction_id": correction_id,
            "operation": operation,
            "affected_id": patch.get("affected_id"),
            "domain": domain,
            "effective": successor is None,
            "superseded_by": successor,
            "supersession_reason": "newer_confirmed_marking_decision" if successor else None,
        })
        if successor is not None:
            continue
        effective.append(correction)
        if domain:
            newer[(target, domain)] = correction_id
            if domain == "mark_scheme":
                # Preserve a still-newer total override as the direct successor.
                newer.setdefault((target, "item_total"), correction_id)
    return list(reversed(effective)), list(reversed(history))


def attach_correction_audit(
    canonical: dict[str, Any],
    corrections: list[dict[str, Any]],
    overlay: dict[str, Any],
) -> None:
    """Keep all confirmed evidence, separating current replay from historical use."""
    states = {item["correction_id"]: item for item in overlay["history"]}
    canonical["corrections"] = [
        {
            "correction_id": str(correction.get("id")),
            "exception_id": correction.get("exception_id"),
            "input_kind": correction.get("input_kind"),
            "display_text": correction.get("display_text"),
            "proposed_patch": copy.deepcopy(correction.get("proposed_patch")),
            "historical_applied_at": correction.get("applied_at"),
            **states[str(correction.get("id"))],
            "confirmation": {
                "required": True, "status": "confirmed",
                "confirmed_at": correction.get("confirmed_at"),
            },
        }
        for correction in corrections
        if correction.get("confirmation_status") == "confirmed"
    ]
    audit = canonical.setdefault("audit", {})
    audit["correction_overlay"] = copy.deepcopy(overlay)
    audit.setdefault("decisions", []).extend([
        {
            "decision_type": "confirmed_correction_overlay",
            "correction_id": item["correction_id"],
            "operation": item["operation"],
            "affected_id": item.get("affected_id"),
            "target_id": item.get("target_id"),
        }
        for item in overlay["applied"]
    ])


SUPPORTED_CORRECTION_OPERATIONS = frozenset({
    "replace_mark_points",
    "set_item_total_override",
    "set_printed_marks",
    "rename_question_identifier",
    "promote_unlabeled_question",
    "insert_missing_major_question",
    "set_question_subtotal",
})

CORRECTION_OPERATION_CATEGORIES = {
    "replace_mark_points": frozenset({
        "mark_arithmetic_mismatch",
        "item_total_mismatch",
        "correction_mark_total_invalid",
    }),
    "set_item_total_override": frozenset({"item_total_mismatch"}),
    "set_printed_marks": frozenset({"multiple_printed_allocations"}),
    "rename_question_identifier": frozenset({
        "numbering_jump",
        "suspicious_question_identifier",
        "scored_major_precedes_subquestions",
    }),
    "promote_unlabeled_question": frozenset({"unlabeled_mark_bearing_question"}),
    "insert_missing_major_question": frozenset({"major_question_gap"}),
    "set_question_subtotal": frozenset({"subtotal_sum_unexpected"}),
}


def correction_operation_supported(category: str, operation: str) -> bool:
    """Return whether the bounded operation is valid for the active exception."""
    return category in CORRECTION_OPERATION_CATEGORIES.get(operation, frozenset())


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
    # Preserve the identifier that actually appears in the immutable source.
    # Canonical numbering may change, but source segmentation must still use
    # the original printed token to recover the associated working.
    q["source_question_id"] = str(q.get("source_question_id") or source_id)
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

    effective, history = effective_correction_history(corrections)
    for correction in effective:
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
        elif category in {"numbering_jump", "suspicious_question_identifier", "scored_major_precedes_subquestions"} and operation in {"accept_suggestion", "rename_question_identifier"} and target_id:
            applied_item, issue = _rename_question_identifier(
                result, correction_id=correction_id, category=category,
                affected_id=affected_id, target_id=target_id,
            )
        else:
            applied_item, issue, handled = apply_phase7_5_patch(
                result,
                normalized,
                correction_id=correction_id,
                category=category,
                affected_id=affected_id,
                operation=operation,
                patch=patch,
            )
            if not handled:
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
    applied_ids = {item["correction_id"] for item in applied}
    for entry in history:
        entry["applied"] = entry["correction_id"] in applied_ids
    result["correction_overlay"] = {
        "confirmed_count": len(history),
        "effective_count": len(effective),
        "superseded_count": len(history) - len(effective),
        "history": history,
        "applied_count": len(applied),
        "issue_count": len(issues),
        "applied": applied,
    }
    _refresh_summary(result)
    return result, applied, issues
