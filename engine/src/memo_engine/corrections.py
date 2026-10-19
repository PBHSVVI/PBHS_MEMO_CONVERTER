from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any

from .structure import (
    derive_source_locator,
    effective_mark_total,
    flatten_units,
    parse_mark_points,
    printed_allocations,
    qtuple,
    source_line_hash,
)
from .phase7_5 import apply_phase7_5_patch
from .visual_evidence import (
    VISUAL_REVIEW_THRESHOLD,
    classify_visual_review_unit,
    ensure_visual_evidence_ids,
    probable_printed_identifier,
    visual_association_review_units,
    visual_association_unit_key,
)

QUESTION_ID_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}$")


def effective_correction_history(
    corrections: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive replay history without changing confirmed evidence or database rows.

    A complete marking replacement retires older schemes and item-total overrides
    on the exact same target. A total-only override retires only earlier total
    overrides: it still needs the current scheme to validate against. Repeated
    grouped allocation decisions supersede as one atomic domain; numbering and
    subtotal operations compose independently.
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
    positions = {str(c.get("id") or ""): i for i, c in enumerate(ordered)}
    explicit_successors: dict[str, tuple[str, str]] = {}
    for i, correction in enumerate(ordered):
        patch = correction.get("proposed_patch") if isinstance(correction.get("proposed_patch"), dict) else {}
        predecessor = str(patch.get("supersedes_correction_id") or "")
        successor = str(correction.get("id") or "")
        if predecessor and successor and positions.get(predecessor, i) < i:
            reason = str(patch.get("supersession_reason") or (
                "teacher_withdrew_previous_change"
                if patch.get("operation") == "withdraw_confirmed_correction"
                else "teacher_amended_previous_change"
            ))
            explicit_successors[predecessor] = (successor, reason)
    newer: dict[tuple[str, str], str] = {}
    history: list[dict[str, Any]] = []
    effective: list[dict[str, Any]] = []
    for correction in reversed(ordered):
        patch = correction.get("proposed_patch")
        patch = patch if isinstance(patch, dict) else {}
        operation = patch.get("operation")
        category = patch.get("category")
        target = str(
            patch.get("candidate_id")
            if operation == "resolve_mark_semantic_conflict"
            else patch.get("review_unit_id")
            if operation == "resolve_visual_evidence_association"
            else patch.get("target_id")
            if operation in {"replace_item_content", "insert_missing_child_question", "resolve_visual_evidence_association"}
            else patch.get("affected_id") or ""
        ).strip()
        correction_id = str(correction.get("id") or "")
        domain = None
        if correction_id and (
            QUESTION_ID_RE.fullmatch(target)
            or operation == "resolve_question_allocation_pairing"
            or operation == "resolve_mark_semantic_conflict"
            or operation == "resolve_visual_evidence_association"
        ):
            if operation == "replace_mark_points" and category in {
                "mark_arithmetic_mismatch", "item_total_mismatch",
                "correction_mark_total_invalid",
            }:
                domain = "mark_scheme"
            elif operation == "set_item_total_override" and category == "item_total_mismatch":
                domain = "item_total"
            elif operation == "replace_item_content":
                domain = "item_content"
            elif operation == "insert_missing_child_question":
                domain = "child_insertion"
            elif (
                operation == "resolve_mark_semantic_conflict"
                and category == "ambiguous_mark_semantics"
            ):
                domain = "mark_semantic"
            elif (
                operation == "resolve_question_allocation_pairing"
                and category == "question_allocation_pairing_ambiguous"
            ):
                domain = "allocation_pairing"
            elif (
                operation == "resolve_visual_evidence_association"
                and category == "visual_evidence_association_uncertain"
            ):
                domain = f"visual_association:{patch.get('review_unit_id') or ''}"
        explicit = explicit_successors.get(correction_id)
        successor = explicit[0] if explicit else (newer.get((target, domain)) if domain else None)
        history.append({
            "correction_id": correction_id,
            "operation": operation,
            "affected_id": patch.get("affected_id"),
            "domain": domain,
            "effective": successor is None,
            "superseded_by": successor,
            "supersession_reason": explicit[1] if explicit else ("newer_confirmed_marking_decision" if successor else None),
        })
        if successor is not None:
            continue
        effective.append(correction)
        if domain:
            newer[(target, domain)] = correction_id
            if domain == "mark_scheme":
                # Preserve a still-newer total override as the direct successor.
                newer.setdefault((target, "item_total"), correction_id)
            elif domain == "item_content" and patch.get("mark_points"):
                # A content correction may include a complete replacement mark
                # scheme. Retire an older scheme while allowing a later,
                # mark-only correction to compose with the corrected content.
                newer.setdefault((target, "mark_scheme"), correction_id)
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
    "replace_item_content",
    "insert_missing_child_question",
    "withdraw_confirmed_correction",
    "replace_mark_points",
    "set_item_total_override",
    "set_printed_marks",
    "rename_question_identifier",
    "promote_unlabeled_question",
    "insert_missing_major_question",
    "set_question_subtotal",
    "resolve_question_allocation_pairing",
})

CORRECTION_OPERATION_CATEGORIES = {
    # Content repair is available for every active review category. Its target
    # and payload are still validated deterministically during application.
    "replace_item_content": frozenset({"*"}),
    "insert_missing_child_question": frozenset({"question_total_mismatch"}),
    "withdraw_confirmed_correction": frozenset({"correction_target_invalid", "correction_evidence_unresolved", "correction_mark_total_invalid"}),
    "resolve_question_allocation_pairing": frozenset({
        "question_allocation_pairing_ambiguous"
    }),
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
        "question_parent_heading_mismatch",
    }),
    "promote_unlabeled_question": frozenset({"unlabeled_mark_bearing_question"}),
    "insert_missing_major_question": frozenset({"major_question_gap"}),
    "set_question_subtotal": frozenset({"subtotal_sum_unexpected"}),
}


def correction_operation_supported(category: str, operation: str) -> bool:
    """Return whether the bounded operation is valid for the active exception."""
    if operation == "replace_item_content" and category == "question_allocation_pairing_ambiguous":
        return False
    categories = CORRECTION_OPERATION_CATEGORIES.get(operation, frozenset())
    return "*" in categories or category in categories


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
    normalized: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    target_id: str,
    source_block_index: int | None = None,
    source_locator: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    source_id = str(affected_id or "")
    if not QUESTION_ID_RE.fullmatch(source_id) or not QUESTION_ID_RE.fullmatch(target_id):
        return None, _issue("correction_target_invalid", affected_id, f"Confirmed correction {correction_id} contains an invalid numbering patch.")
    candidates = [q for q in structure.get("questions", []) if str(q.get("question_id")) == source_id]
    matches = list(candidates)
    resolution_method = "question_identifier"
    if source_block_index is not None:
        supplied_locator = isinstance(source_locator, dict)
        locator = source_locator if supplied_locator else (
            derive_source_locator(normalized, source_id, source_block_index)
            if isinstance(normalized.get("content"), dict) else None
        )
        if locator is not None and (
            locator.get("schema_version") != "1.0"
            or str(locator.get("source_question_id") or "") != source_id
            or locator.get("source_page") is None
            or locator.get("parent_heading") is None
            or not re.fullmatch(r"[0-9a-f]{64}", str(locator.get("source_line_hash") or ""))
        ):
            locator = None
        exact = [
            q for q in candidates
            if q.get("source_block_index") is not None
            and int(q.get("source_block_index")) == source_block_index
        ]
        exact_compatible = len(exact) == 1 and (
            locator is not None or (not supplied_locator and "content" not in normalized)
        )
        if exact_compatible and locator is not None:
            exact_question = exact[0]
            locator_page = locator.get("source_page")
            locator_heading = locator.get("parent_heading")
            locator_hash = str(locator.get("source_line_hash") or "")
            exact_compatible = (
                (locator_page is None or exact_question.get("source_page") == locator_page)
                and (locator_heading is None or str(exact_question.get("source_heading_major")) == str(locator_heading))
                and (not locator_hash or str(exact_question.get("source_line_hash") or source_line_hash(exact_question.get("source_line"))) == locator_hash)
            )
        if exact_compatible:
            matches = exact
            resolution_method = "exact_source_block"
        else:
            resolution_method = "stable_source_rebase" if supplied_locator else "legacy_source_rebase"
            if locator is None:
                matches = []
            else:
                locator_page = locator.get("source_page")
                locator_heading = locator.get("parent_heading")
                locator_hash = str(locator.get("source_line_hash") or "")
                matches = []
                for question in candidates:
                    if locator_page is not None and question.get("source_page") != locator_page:
                        continue
                    if locator_heading is not None and str(question.get("source_heading_major")) != str(locator_heading):
                        continue
                    question_hash = str(question.get("source_line_hash") or source_line_hash(question.get("source_line")))
                    if locator_hash and question_hash != locator_hash:
                        continue
                    matches.append(question)
            source_locator = locator
    elif isinstance(source_locator, dict):
        locator_page = source_locator.get("source_page")
        locator_heading = source_locator.get("parent_heading")
        locator_hash = str(source_locator.get("source_line_hash") or "")
        matches = [q for q in candidates if
            (locator_page is None or q.get("source_page") == locator_page)
            and (locator_heading is None or str(q.get("source_heading_major")) == str(locator_heading))
            and (not locator_hash or str(q.get("source_line_hash") or source_line_hash(q.get("source_line"))) == locator_hash)
        ]
        resolution_method = "stable_source_locator"
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
    q["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "rename_question_identifier",
        "source_id": source_id,
        "source_block_index": q.get("source_block_index"),
    }
    structure["questions"].sort(key=lambda item: (int(item.get("source_block_index", 10**9)), tuple(item.get("path") or (999,))))
    _remove_exception(structure, category, affected_id)
    _remove_exception(structure, "question_parent_heading_mismatch", affected_id)
    locator_resolution = {
        "method": resolution_method,
        "original_source_block_index": source_block_index,
        "resolved_source_block_index": q.get("source_block_index"),
        "source_page": q.get("source_page"),
        "parent_heading": q.get("source_heading_major"),
    }
    return {
        "correction_id": correction_id,
        "operation": "rename_question_identifier",
        "category": category,
        "affected_id": source_id,
        "target_id": target_id,
        "source_block_index": q.get("source_block_index"),
        "locator_resolution": locator_resolution,
    }, None


def _apply_visual_evidence_association(
    structure: dict[str, Any],
    visual: dict[str, Any] | None,
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Apply one teacher decision to exactly one physical visual review unit."""
    decision = str(patch.get("decision") or "").upper()
    evidence_ids = patch.get("evidence_ids")
    asset = str(patch.get("rendered_asset_ref") or "")
    owned = str(patch.get("original_owned_question_ref") or "")
    association_status = str(patch.get("association_status") or "")
    review_unit_id = str(patch.get("review_unit_id") or "")
    target_id = str(patch.get("target_id") or "").strip()
    try:
        page = int(patch.get("source_page"))
    except (TypeError, ValueError):
        page = -1
    if (
        patch.get("schema_version") != "1.0"
        or decision not in {"ACCEPT", "REASSIGN", "REJECT"}
        or not isinstance(evidence_ids, list)
        or not evidence_ids
        or len(evidence_ids) > 200
        or len(set(map(str, evidence_ids))) != len(evidence_ids)
        or not asset.startswith("internal/visual/")
        or ".." in asset
        or page < 1
        or not review_unit_id
        or not isinstance(visual, dict)
    ):
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} does not identify one valid physical visual review unit.",
        )

    evidence_items = [
        item for item in visual.get("evidence") or [] if isinstance(item, dict)
    ]
    mark_change_items = [
        item for item in visual.get("mark_changes") or [] if isinstance(item, dict)
    ]
    ensure_visual_evidence_ids(evidence_items)
    ensure_visual_evidence_ids(mark_change_items)
    raw_items = [*evidence_items, *mark_change_items]
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in raw_items:
        evidence_id = str(item.get("evidence_id") or "")
        if evidence_id:
            by_id.setdefault(evidence_id, []).append(item)
    selected: list[dict[str, Any]] = []
    for evidence_id in map(str, evidence_ids):
        matches = by_id.get(evidence_id, [])
        if len(matches) != 1:
            return None, _issue(
                "correction_evidence_unresolved", affected_id,
                f"Confirmed correction {correction_id} does not resolve every visual evidence identifier exactly once.",
            )
        selected.append(matches[0])

    def matches_physical(item: dict[str, Any]) -> bool:
        key = visual_association_unit_key(item)
        return key[0] == asset and key[1] == page and key[2] == owned and (
            key[3] == association_status
            or association_status == "unresolved_question"
        )

    if not selected or not all(matches_physical(item) for item in selected):
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} does not match the stored visual asset, page, owner, and association status.",
        )
    physical = selected if association_status == "unresolved_question" else [
        item for item in raw_items if matches_physical(item)
    ]
    physical_ids = [str(item.get("evidence_id")) for item in physical]
    classification = classify_visual_review_unit(physical)
    unit_classification = str(patch.get("unit_classification") or classification["classification"])
    selection_mode = str(patch.get("selection_mode") or "legacy_whole_unit")
    displayed_ids = patch.get("review_unit_evidence_ids")
    modern_selection = selection_mode in {"whole_unit", "explicit_subset"}
    if modern_selection and (
        unit_classification != classification["classification"]
        or not isinstance(displayed_ids, list)
        or len(displayed_ids) != len(set(map(str, displayed_ids)))
        or set(map(str, displayed_ids)) != set(physical_ids)
    ):
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} does not match the displayed visual review classification.",
        )
    requires_complete = (
        decision == "REJECT"
        or not modern_selection
        or unit_classification == "normal"
        or selection_mode == "whole_unit"
    )
    if requires_complete and set(map(str, evidence_ids)) != set(physical_ids):
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} covers only part of the physical visual review unit.",
        )
    if (
        modern_selection
        and unit_classification in {"mixed", "runaway_model_output"}
        and decision != "REJECT"
        and selection_mode != "explicit_subset"
    ):
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} did not explicitly select mixed visual observations.",
        )
    unit_items = [
        {**item, "association_status": association_status}
        if association_status == "unresolved_question" else item
        for item in physical
    ]
    units = visual_association_review_units(unit_items)
    if len(units) != 1 or units[0].get("review_unit_id") != review_unit_id:
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} no longer matches one stable visual review unit.",
        )
    unit = units[0]
    provenance_unit = visual_association_review_units(selected)[0] if modern_selection else unit
    if (
        patch.get("source_page_bboxes") != provenance_unit.get("source_page_bboxes")
        or patch.get("owned_bbox") != provenance_unit.get("owned_bbox")
        or patch.get("original_claimed_question_refs") != provenance_unit.get("claimed_question_refs")
    ):
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} does not match the stored visual provenance.",
        )

    questions = [item for item in structure.get("questions", []) if isinstance(item, dict)]
    target_matches = [item for item in questions if str(item.get("question_id") or "") == target_id]
    if decision != "REJECT" and len(target_matches) != 1:
        return None, _issue(
            "correction_target_invalid", target_id or affected_id,
            f"Confirmed correction {correction_id} does not identify one current parsed question.",
        )
    if decision == "REJECT" and target_id:
        return None, _issue(
            "correction_target_invalid", affected_id,
            f"Confirmed correction {correction_id} must not assign a target when rejecting visual evidence.",
        )
    if decision == "ACCEPT":
        owner_matches = [item for item in questions if (
            str(item.get("question_id") or "") == owned
            or str(item.get("source_question_id") or "") == owned
        )]
        page_matches = [item for item in owner_matches if (
            item.get("source_page") == page
            or (
                isinstance(item.get("source_ref"), dict)
                and item["source_ref"].get("page") == page
            )
        )]
        if page_matches:
            owner_matches = page_matches
        if len(owner_matches) != 1 or target_id != str(owner_matches[0].get("question_id") or ""):
            return None, _issue(
                "correction_target_invalid", target_id or affected_id,
                f"Confirmed correction {correction_id} does not accept the evidence for its bounded current owner.",
            )
    if decision == "REASSIGN" and not QUESTION_ID_RE.fullmatch(target_id):
        return None, _issue(
            "correction_target_invalid", target_id or affected_id,
            f"Confirmed correction {correction_id} does not contain one explicit parsed reassignment target.",
        )

    if decision != "REJECT":
        target = target_matches[0]
        solution_signatures = {
            (
                str(item.get("text") or "").strip().casefold(),
                str(item.get("rendered_asset_ref") or ""),
            )
            for item in target.get("visual_solution_segments", [])
            if isinstance(item, dict)
        }
        for item in selected:
            resolved = copy.deepcopy(item)
            resolved["effective"] = True
            resolved["evidence_status"] = "teacher_association_accepted" if decision == "ACCEPT" else "teacher_association_reassigned"
            resolved["association_resolution"] = {
                "correction_id": correction_id,
                "decision": decision,
                "review_unit_id": review_unit_id,
                "original_owned_question_ref": owned or None,
                "original_claimed_question_ref": item.get("question_ref"),
                "target_question_ref": target_id,
            }
            if "visual_value" in item and "level" in item:
                target.setdefault("visual_mark_change_evidence", []).append(resolved)
                structure.setdefault("exceptions", []).append({
                    "level": "amber", "category": "visual_mark_change_review",
                    "affected_id": target_id,
                    "message": "A teacher-associated handwritten mark allocation still requires bounded mark confirmation.",
                    "suggestions": [{
                        "printed_value": item.get("printed_value"),
                        "visual_value": item.get("visual_value"),
                        "level": item.get("level"),
                        "rendered_asset_ref": asset,
                        "evidence_id": item.get("evidence_id"),
                    }],
                })
                continue
            target.setdefault("visual_evidence", []).append(resolved)
            if (
                item.get("kind") in {"answer", "answer_working", "diagram_entry"}
                and not item.get("math_normalization_issue")
                and not (
                    item.get("evidence_status") == "printed_source_rediscovery"
                    or modern_selection
                    and unit_classification in {"mixed", "runaway_model_output"}
                    and probable_printed_identifier(item)
                )
                and float(item.get("confidence") or 0) >= VISUAL_REVIEW_THRESHOLD
            ):
                text = str(item.get("normalized_math") or item.get("transcription") or "").strip()
                signature = (text.casefold(), asset)
                if text and signature not in solution_signatures:
                    target.setdefault("visual_solution_segments", []).append({
                        "text": text,
                        "raw_transcription": item.get("transcription"),
                        "source_ref": {"file_id": "source_1", "page": page},
                        "rendered_asset_ref": asset,
                        "confidence": float(item.get("confidence") or 0),
                        "canonical_latex": item.get("normalized_math"),
                        "association_resolution": copy.deepcopy(resolved["association_resolution"]),
                    })
                    solution_signatures.add(signature)

    def same_review_unit(exception: dict[str, Any]) -> bool:
        if exception.get("category") != category:
            return False
        for suggestion in exception.get("suggestions") or []:
            if not isinstance(suggestion, dict):
                continue
            if suggestion.get("review_unit_id") == review_unit_id:
                return True
            try:
                suggestion_page = int(suggestion.get("page"))
            except (TypeError, ValueError):
                suggestion_page = -1
            if (
                str(suggestion.get("rendered_asset_ref") or "") == asset
                and suggestion_page == page
                and str(suggestion.get("owned_question_ref") or exception.get("affected_id") or "") == owned
            ):
                return True
        return False

    structure["exceptions"] = [
        exception for exception in structure.get("exceptions", [])
        if not same_review_unit(exception)
    ]
    return {
        "correction_id": correction_id,
        "operation": "resolve_visual_evidence_association",
        "category": category,
        "affected_id": affected_id,
        "target_id": target_id or None,
        "decision": decision,
        "selection_mode": selection_mode,
        "unit_classification": unit_classification,
        "selected_evidence_count": len(selected),
        "review_unit_id": review_unit_id,
        "evidence_ids": list(map(str, evidence_ids)),
        "rendered_asset_ref": asset,
        "source_page": page,
        "original_owned_question_ref": owned or None,
        "original_claimed_question_refs": copy.deepcopy(unit.get("claimed_question_refs")),
        "source_page_bboxes": copy.deepcopy(unit.get("source_page_bboxes")),
        "owned_bbox": copy.deepcopy(unit.get("owned_bbox")),
    }, None


def apply_confirmed_corrections(
    structure: dict[str, Any],
    normalized: dict[str, Any],
    corrections: list[dict[str, Any]],
    visual: dict[str, Any] | None = None,
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
        if category == "visual_evidence_association_uncertain" and operation == "resolve_visual_evidence_association":
            applied_item, issue = _apply_visual_evidence_association(
                result, visual, correction_id=correction_id, category=category,
                affected_id=affected_id, patch=patch,
            )
        elif category == "unlabeled_mark_bearing_question" and operation in {"accept_suggestion", "promote_unlabeled_question"} and target_id:
            applied_item, issue = _promote_unlabeled_question(
                result, normalized, correction_id=correction_id, category=category,
                affected_id=affected_id, target_id=target_id,
            )
        elif (
            (
                category in {"numbering_jump", "suspicious_question_identifier", "scored_major_precedes_subquestions", "duplicate_question_identifier"}
                and operation in {"accept_suggestion", "rename_question_identifier"}
            )
            or (category == "question_parent_heading_mismatch" and operation == "rename_question_identifier")
        ) and target_id:
            source_block_index = None
            if patch.get("source_block_index") is not None:
                try:
                    source_block_index = int(patch["source_block_index"])
                except (TypeError, ValueError):
                    issue = _issue(
                        "correction_target_invalid", affected_id,
                        f"Confirmed correction {correction_id} contains an invalid source occurrence locator.",
                    )
                    source_block_index = None
            if issue:
                applied_item = None
            else:
                applied_item, issue = _rename_question_identifier(
                    result, normalized, correction_id=correction_id, category=category,
                    affected_id=affected_id, target_id=target_id,
                    source_block_index=source_block_index,
                    source_locator=patch.get("source_locator") if isinstance(patch.get("source_locator"), dict) else None,
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
    applied_by_id = {item["correction_id"]: item for item in applied}
    for entry in history:
        entry["applied"] = entry["correction_id"] in applied_ids
        resolution = applied_by_id.get(entry["correction_id"], {}).get("locator_resolution")
        if isinstance(resolution, dict):
            entry["locator_resolution"] = copy.deepcopy(resolution)
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
