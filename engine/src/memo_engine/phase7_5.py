from __future__ import annotations

import copy
import re
from typing import Any

from .structure import (
    effective_mark_total,
    find_question_ids,
    flatten_units,
    parse_mark_points,
    printed_allocations,
    qtuple,
    semantic_for_code,
)

QUESTION_ID_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}$")
QUESTION_TOKEN_ANY_RE = re.compile(
    r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){0,2})(?![\d.])"
)
MARK_TOTAL_RE = re.compile(r"(?i)\b(\d{1,2})\s*marks?\b")
TEACHER_ITEM_TOTAL_RE = re.compile(
    r"(?i)^\s*(?:(?:award|use|make(?:\s+it)?|total(?:\s+is)?|"
    r"set(?:\s+(?:the\s+)?(?:item\s+)?total(?:\s+to)?)?)\s+)?"
    r"(\d{1,2})\s*marks?\s*[.!]?\s*$"
)
BARE_ITEM_TOTAL_RE = re.compile(r"^\s*\(\s*(\d{1,2})\s*\)\s*$")
NATURAL_ITEM_TOTAL_RE = re.compile(
    r"(?i)^\s*(?:this\s+(?:question|item)\s+is\s+worth|"
    r"the\s+total\s+(?:for\s+this\s+(?:question|item)\s+)?is)\s+"
    r"(\d{1,2})\s*marks?\s*[.!]?\s*$"
)
CORRECTED_PAREN_TOTAL_RE = re.compile(
    r"(?i)^\s*the\s*\(\s*\d{1,2}\s*\)\s+is\s+wrong\s*[,;]?\s*"
    r"it\s+should\s+be\s*\(\s*(\d{1,2})\s*\)\s*[.!]?\s*$"
)
SUBTOTAL_INSTRUCTION_RE = re.compile(
    r"(?i)\bq(?:uestion)?\s*(\d{1,2})\b.*?\b(?:sub\s*total|subtotal|total)"
    r"\s*(?:of|to|=|as|is)?\s*[\[(]?\s*(\d{1,3})\b"
)
SUBTOTAL_FIRST_INSTRUCTION_RE = re.compile(
    r"(?i)\b(?:sub\s*total|subtotal|total)\s*(?:of|to|=|as|is)?\s*"
    r"[\[(]?\s*(\d{1,3})\b.*?\bq(?:uestion)?\s*(\d{1,2})\b"
)
MAJOR_QUESTION_INSTRUCTION_RE = re.compile(
    r"(?i)\b(?:question|q)\s*(\d{1,2})\b"
)

PHASE7_5_REINTERPRET_CATEGORIES = {
    "multiple_printed_allocations",
    "mark_arithmetic_mismatch",
    "item_total_mismatch",
    "correction_mark_total_invalid",
    "subtotal_sum_unexpected",
    "major_question_gap",
    "scored_major_precedes_subquestions",
}

MAX_ASSESSMENT_TOTAL = 999
MARK_CODES = {"M", "A", "CA", "F", "S", "R", "S/R", "SF", "AO"}
GROUPED_ALLOCATION_CATEGORY = "question_allocation_pairing_ambiguous"

CONTENT_CORRECTION_START = "[[PBHS_CONTENT_CORRECTION_V1]]"
CONTENT_CORRECTION_END = "[[END_PBHS_CONTENT_CORRECTION_V1]]"
CONTENT_INTENT_RE = re.compile(
    r"(?is)\b(?:question|prompt|answer\s*box|memo\s*(?:answer|working)|solution)\b"
    r".{0,80}\b(?:incorrect|wrong|replace|should\s+(?:be|read|say)|needs?\s+(?:changing|correction))\b"
    r"|\b(?:incorrect|wrong|replace)\b.{0,80}\b(?:question|prompt|answer\s*box|memo|solution)\b"
)


def _structured_content_proposal(
    exception: dict[str, Any], evidence_text: str
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    """Parse the review page's explicit, versioned content-correction envelope."""
    evidence: dict[str, Any] = {"structured_content_correction": False}
    text = evidence_text.strip()
    if not text.startswith(CONTENT_CORRECTION_START):
        return None, None, evidence
    evidence["structured_content_correction"] = True
    if str(exception.get("category") or "") == GROUPED_ALLOCATION_CATEGORY:
        return None, None, evidence
    if not text.endswith(CONTENT_CORRECTION_END):
        return None, None, evidence

    body = text[len(CONTENT_CORRECTION_START):-len(CONTENT_CORRECTION_END)].strip()
    match = re.fullmatch(
        r"TARGET:\s*(?P<target>[^\n]+)\n"
        r"QUESTION:\n(?P<question>.*?)\n"
        r"ANSWER:\n(?P<answer>.*?)\n"
        r"MARKING:\n(?P<marking>.*)",
        body,
        flags=re.S,
    )
    if not match:
        return None, None, evidence
    target = match.group("target").strip()
    question_text = match.group("question").strip()
    solution_lines = [line.strip() for line in match.group("answer").splitlines() if line.strip()]
    marking_text = match.group("marking").strip()
    evidence.update({
        "target_id": target,
        "has_question_text": bool(question_text),
        "solution_line_count": len(solution_lines),
        "has_marking_text": bool(marking_text),
    })
    affected = str(exception.get("affected_id") or "").strip()
    if (
        not QUESTION_ID_RE.fullmatch(target)
        or (QUESTION_ID_RE.fullmatch(affected) and target != affected)
        or (not question_text and not solution_lines)
    ):
        return None, None, evidence

    patch: dict[str, Any] = {
        "schema_version": "1.0",
        "operation": "replace_item_content",
        "category": str(exception.get("category") or ""),
        "affected_id": exception.get("affected_id"),
        "target_id": target,
        "question_text": question_text or None,
        "solution_lines": solution_lines,
        "reinterpretation_method": "deterministic_structured_content_correction",
    }
    if marking_text:
        normalized_marking = re.sub(
            r"\s+(?:and|,|;)\s+(?=\d+\s*(?:CA|M|A|F|S|R)\b)",
            "\n",
            marking_text,
            flags=re.I,
        )
        points = parse_mark_points(normalized_marking)
        total, calc_mode = effective_mark_total(points, normalized_marking)
        if not points or total <= 0:
            return None, None, evidence
        patch.update({
            "mark_points": points,
            "expected_total": total,
            "mark_calculation_mode": calc_mode,
        })
        evidence["parsed_mark_total"] = total
    display = f"Replace the question or memo content for Question {target}"
    if patch.get("mark_points"):
        display += f" and use the supplied {patch['expected_total']}-mark scheme"
    return patch, display + ".", evidence


def _issue(
    category: str,
    affected_id: str | None,
    message: str,
    level: str = "red",
) -> dict[str, Any]:
    return {
        "level": level,
        "category": category,
        "affected_id": affected_id,
        "message": message,
        "suggestions": [],
    }


def _exception_exists(
    structure: dict[str, Any],
    category: str,
    affected_id: str | None,
) -> bool:
    return any(
        str(item.get("category")) == category
        and item.get("affected_id") == affected_id
        for item in structure.get("exceptions", [])
    )


def _remove_exception(
    structure: dict[str, Any],
    category: str,
    affected_id: str | None,
) -> None:
    structure["exceptions"] = [
        item
        for item in structure.get("exceptions", [])
        if not (
            str(item.get("category")) == category
            and item.get("affected_id") == affected_id
        )
    ]


def _refresh_summary(structure: dict[str, Any]) -> None:
    questions = structure.get("questions") or []
    exceptions = structure.get("exceptions") or []
    subtotals = structure.get("subtotals") or []
    summary = dict(structure.get("summary") or {})
    summary["detected_identifier_count"] = len(questions)
    summary["leaf_question_count"] = sum(
        1 for question in questions if not question.get("context_only")
    )
    summary["unique_question_count"] = len(
        {str(question.get("question_id")) for question in questions}
    )
    summary["subtotal_count"] = len(subtotals)
    summary["subtotal_sum"] = sum(
        int(item.get("value") or 0) for item in subtotals
    )
    summary["amber_count"] = sum(
        1 for item in exceptions if item.get("level") == "amber"
    )
    summary["red_count"] = sum(
        1 for item in exceptions if item.get("level") == "red"
    )
    summary["review_required"] = bool(exceptions)
    structure["summary"] = summary


def _candidate_between(
    questions: list[dict[str, Any]],
    block_index: int,
) -> str | None:
    before = [
        question
        for question in questions
        if int(question.get("source_block_index", -1)) < block_index
        and not question.get("context_only")
    ]
    after = [
        question
        for question in questions
        if int(question.get("source_block_index", 10**9)) > block_index
        and not question.get("context_only")
    ]
    if not before or not after:
        return None

    previous = max(
        before, key=lambda item: int(item.get("source_block_index", -1))
    )
    following = min(
        after, key=lambda item: int(item.get("source_block_index", 10**9))
    )
    try:
        left = qtuple(str(previous["question_id"]))
        right = qtuple(str(following["question_id"]))
    except Exception:
        return None

    if (
        len(left) == len(right)
        and len(left) >= 2
        and left[:-1] == right[:-1]
        and right[-1] == left[-1] + 2
    ):
        return ".".join(map(str, (*left[:-1], left[-1] + 1)))
    return None


def enrich_structure_phase7_5(
    structure: dict[str, Any],
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """
    Expose only bounded cause-level Phase 7.5 review findings.

    Enrichment never changes numbering or marks. Mutations still require a
    confirmed correction overlay.
    """
    questions = structure.get("questions") or []
    blocks = flatten_units(normalized)
    known_unlabelled = {
        int(item.get("block_index", -1))
        for item in structure.get("unlabeled_mark_blocks", [])
    }

    # Marking-only row between x.1 and x.3 (RAW 5.2).
    for block_index, block in enumerate(blocks):
        if block_index in known_unlabelled:
            continue
        if find_question_ids(str(block.get("source") or "")):
            continue
        allocations = printed_allocations(str(block.get("allocation") or ""))
        if len(allocations) != 1:
            continue
        if not str(block.get("marking") or "").strip():
            continue
        candidate = _candidate_between(questions, block_index)
        if not candidate:
            continue
        if any(
            str(question.get("question_id")) == candidate
            for question in questions
        ):
            continue

        structure.setdefault("unlabeled_mark_blocks", []).append({
            "block_index": block_index,
            "printed_allocations": allocations,
            "candidate": candidate,
            "phase7_5_evidence": "marking_only_sequence_gap",
        })
        _remove_exception(structure, "possible_missing_question", candidate)
        if not _exception_exists(
            structure, "unlabeled_mark_bearing_question", candidate
        ):
            structure.setdefault("exceptions", []).append({
                "level": "amber",
                "category": "unlabeled_mark_bearing_question",
                "affected_id": candidate,
                "message": (
                    "A marking-only memo row has no printed question identifier; "
                    f"the surrounding sequence supports Question {candidate}."
                ),
                "suggestions": [{
                    "kind": "review_numbering",
                    "candidate": candidate,
                }],
            })

    # Scored major followed by .2 (RAW 8 -> 8.1).
    qids = {str(question.get("question_id")) for question in questions}
    for question in questions:
        qid = str(question.get("question_id") or "")
        if not re.fullmatch(r"\d{1,2}", qid):
            continue
        if question.get("context_only"):
            continue
        if not (
            question.get("printed_marks") is not None
            or int(question.get("computed_shorthand_marks") or 0) > 0
        ):
            continue
        major = int(qid)
        child_ids = sorted(
            [other for other in qids if other.startswith(f"{major}.")],
            key=qtuple,
        )
        target = f"{major}.1"
        if target in qids or not child_ids:
            continue
        first_child = qtuple(child_ids[0])
        if len(first_child) < 2 or first_child[1] != 2:
            continue
        if not _exception_exists(
            structure, "scored_major_precedes_subquestions", qid
        ):
            structure.setdefault("exceptions", []).append({
                "level": "amber",
                "category": "scored_major_precedes_subquestions",
                "affected_id": qid,
                "message": (
                    f"Scored Question {qid} is followed by {child_ids[0]}; "
                    f"confirm whether the scored row is Question {target}."
                ),
                "suggestions": [{
                    "kind": "review_numbering",
                    "candidate": target,
                }],
            })

    _refresh_summary(structure)
    return structure


def _question(
    structure: dict[str, Any],
    question_id: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in structure.get("questions", [])
        if str(item.get("question_id")) == question_id
    ]
    return matches[0] if len(matches) == 1 else None


def _source_block(
    normalized: dict[str, Any],
    question: dict[str, Any],
) -> dict[str, Any] | None:
    blocks = flatten_units(normalized)
    index = int(question.get("source_block_index", -1))
    if 0 <= index < len(blocks):
        return blocks[index]
    return None


def _apply_set_printed_marks(
    structure: dict[str, Any],
    normalized: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    question = _question(structure, affected_id)
    if question is None:
        return None, _issue(
            "correction_evidence_unresolved",
            affected_id,
            f"Confirmed correction {correction_id} could not resolve Question {affected_id}.",
        )
    try:
        chosen = int(patch.get("printed_marks"))
    except Exception:
        chosen = 0
    if not 1 <= chosen <= 20:
        return None, _issue(
            "correction_mark_total_invalid",
            affected_id,
            f"Confirmed correction {correction_id} does not contain a safe printed mark total.",
        )

    block = _source_block(normalized, question)
    allocations = (
        printed_allocations(str(block.get("allocation") or ""))
        if block is not None
        else []
    )
    if len(allocations) < 2 or chosen not in allocations:
        return None, _issue(
            "correction_evidence_unresolved",
            affected_id,
            (
                f"Confirmed correction {correction_id} selected {chosen} marks, "
                "but that value is not one of the ambiguous printed source allocations."
            ),
        )

    question["printed_marks"] = chosen
    question["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "set_printed_marks",
    }
    _remove_exception(structure, category, affected_id)
    if int(question.get("computed_shorthand_marks") or 0) == chosen:
        _remove_exception(structure, "mark_arithmetic_mismatch", affected_id)
    return {
        "correction_id": correction_id,
        "operation": "set_printed_marks",
        "category": category,
        "affected_id": affected_id,
        "target_id": affected_id,
        "printed_marks": chosen,
        "source_block_index": question.get("source_block_index"),
    }, None



def _apply_set_item_total_override(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    question = _question(structure, affected_id)
    if question is None:
        return None, _issue(
            "correction_evidence_unresolved",
            affected_id,
            f"Confirmed correction {correction_id} could not resolve Question {affected_id}.",
        )

    try:
        chosen = int(patch.get("printed_marks"))
    except Exception:
        chosen = 0
    if not 1 <= chosen <= 20:
        return None, _issue(
            "correction_mark_total_invalid",
            affected_id,
            f"Confirmed correction {correction_id} does not contain a safe item total.",
        )

    computed = int(question.get("computed_shorthand_marks") or 0)
    if computed <= 0:
        return None, _issue(
            "correction_evidence_unresolved",
            affected_id,
            f"Question {affected_id} has no bounded computed mark total to reconcile.",
        )
    if chosen != computed:
        return None, _issue(
            "correction_mark_total_invalid",
            affected_id,
            (
                f"Teacher total {chosen} does not match the existing computed mark "
                f"scheme total {computed} for Question {affected_id}; provide the "
                "replacement mark scheme instead."
            ),
        )

    original = question.get("printed_marks")
    question["printed_marks"] = chosen
    question["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "set_item_total_override",
        "source_printed_marks": original,
    }
    _remove_exception(structure, category, affected_id)
    _remove_exception(structure, "mark_arithmetic_mismatch", affected_id)

    return {
        "correction_id": correction_id,
        "operation": "set_item_total_override",
        "category": category,
        "affected_id": affected_id,
        "target_id": affected_id,
        "source_printed_marks": original,
        "printed_marks": chosen,
        "mark_total": computed,
        "source_block_index": question.get("source_block_index"),
    }, None

def _apply_replace_mark_points(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    question = _question(structure, affected_id)
    if question is None:
        return None, _issue(
            "correction_evidence_unresolved",
            affected_id,
            f"Confirmed correction {correction_id} could not resolve Question {affected_id}.",
        )

    raw_points = patch.get("mark_points")
    if not isinstance(raw_points, list) or not raw_points:
        return None, _issue(
            "correction_mark_scheme_invalid",
            affected_id,
            f"Confirmed correction {correction_id} has no structured mark scheme.",
        )

    points: list[dict[str, Any]] = []
    for item in raw_points:
        if not isinstance(item, dict):
            return None, _issue(
                "correction_mark_scheme_invalid",
                affected_id,
                f"Confirmed correction {correction_id} contains an invalid mark point.",
            )
        try:
            count = int(item.get("count") or 0)
        except Exception:
            count = 0
        descriptor = str(item.get("descriptor") or "").strip()
        if not 1 <= count <= 10 or not descriptor:
            return None, _issue(
                "correction_mark_scheme_invalid",
                affected_id,
                (
                    f"Confirmed correction {correction_id} contains a mark point "
                    "without a bounded count and descriptor."
                ),
            )
        points.append({
            "count": count,
            "code": item.get("code"),
            "descriptor": descriptor,
            "semantic": item.get("semantic") or "other",
            "source": item.get("source")
            or f"{count}{item.get('code') or ''} {descriptor}".strip(),
            "notation": "teacher_confirmed",
        })

    teacher_marking_text = "\n".join(
        str(item.get("source") or "").strip()
        for item in points
        if str(item.get("source") or "").strip()
    )
    total, calc_mode = effective_mark_total(points, teacher_marking_text)
    observed = question.get("printed_marks")
    if observed is not None and total != int(observed):
        return None, _issue(
            "correction_mark_total_invalid",
            affected_id,
            (
                f"Confirmed correction {correction_id} supplies {total} marks, "
                f"but the source prints ({observed})."
            ),
        )
    expected_total = patch.get("expected_total")
    if expected_total is not None and total != int(expected_total):
        return None, _issue(
            "correction_mark_total_invalid",
            affected_id,
            f"Confirmed correction {correction_id} does not match its interpreted total.",
        )

    question["mark_points"] = points
    question["computed_shorthand_marks"] = total
    question["mark_calculation_mode"] = calc_mode
    question["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "replace_mark_points",
    }
    _remove_exception(structure, category, affected_id)
    _remove_exception(structure, "mark_arithmetic_mismatch", affected_id)
    return {
        "correction_id": correction_id,
        "operation": "replace_mark_points",
        "category": category,
        "affected_id": affected_id,
        "target_id": affected_id,
        "mark_total": total,
        "mark_calculation_mode": calc_mode,
        "source_block_index": question.get("source_block_index"),
    }, None


def _apply_resolve_mark_semantic_conflict(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    question = _question(structure, affected_id)
    # Semantic exceptions are produced after the correction overlay stage and
    # therefore are not present in the freshly extracted structure.  The Edge
    # Function binds the correction to the active database exception; replay
    # validates the exact question and source point below.
    if question is None:
        return None, _issue(
            "correction_evidence_unresolved", affected_id,
            f"Confirmed correction {correction_id} could not resolve the active semantic conflict for Question {affected_id}.",
        )

    try:
        mark_index = int(patch.get("mark_index"))
        source_count = int(patch.get("source_count"))
    except (TypeError, ValueError):
        mark_index = -1
        source_count = 0
    candidate_id = str(patch.get("candidate_id") or "")
    expected_candidate = f"{affected_id.replace('.', '_')}__m{mark_index + 1}"
    points = question.get("mark_points") or []
    if (
        mark_index < 0
        or mark_index >= len(points)
        or candidate_id != expected_candidate
    ):
        return None, _issue(
            "correction_semantic_target_invalid", affected_id,
            f"Confirmed correction {correction_id} does not identify one current marking point.",
        )

    point = points[mark_index]
    source_code = str(patch.get("source_code") or "").upper()
    source_descriptor = str(patch.get("source_descriptor") or "").strip()
    if (
        int(point.get("count") or 0) != source_count
        or str(point.get("code") or "").upper() != source_code
        or str(point.get("descriptor") or "").strip() != source_descriptor
    ):
        return None, _issue(
            "correction_semantic_source_changed", affected_id,
            f"Confirmed correction {correction_id} no longer matches the source marking point.",
        )

    selected_code = str(patch.get("selected_code") or "").upper()
    selected_semantic = str(patch.get("selected_semantic_type") or "")
    allowed_by_code = {
        "M": {"method"},
        "CA": {"consistent_accuracy"},
        "R": {"reason"},
        "A": {"accuracy", "answer"},
        "F": {"formula", "factorisation"},
        # Historical corrections may contain the legacy S meanings. New teacher
        # choices are constrained by the ordinary-Mathematics Edge profile.
        "S": {"statement", "substitution", "simplification"},
        "S/R": {"statement_reason"},
        "SF": {"substitution"},
        "AO": {"answer_only"},
    }
    if selected_semantic not in allowed_by_code.get(selected_code, set()):
        return None, _issue(
            "correction_semantic_choice_invalid", affected_id,
            f"Confirmed correction {correction_id} contains an incompatible marking code and meaning.",
        )

    point["code"] = selected_code
    point["semantic"] = selected_semantic
    point["source"] = f"{source_count}{selected_code} {source_descriptor}".strip()
    point["notation"] = "teacher_semantic_confirmed"
    question["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "resolve_mark_semantic_conflict",
        "candidate_id": candidate_id,
    }
    _remove_exception(structure, category, affected_id)
    return {
        "correction_id": correction_id,
        "operation": "resolve_mark_semantic_conflict",
        "category": category,
        "affected_id": affected_id,
        "target_id": affected_id,
        "candidate_id": candidate_id,
        "mark_index": mark_index,
        "selected_code": selected_code,
        "selected_semantic_type": selected_semantic,
        "source_block_index": question.get("source_block_index"),
    }, None


def _apply_replace_item_content(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if category == GROUPED_ALLOCATION_CATEGORY:
        return None, _issue(
            "correction_operation_invalid",
            affected_id,
            "A grouped allocation exception must be resolved for every listed question together.",
        )
    target_id = str(patch.get("target_id") or affected_id or "").strip()
    active_id = str(affected_id or "").strip()
    replacement_id = str(patch.get("replacement_id") or target_id).strip()
    child_repair = patch.get("reconciliation_scope") == "suspicious_child"
    valid_child_scope = (
        child_repair
        and category == "question_total_mismatch"
        and QUESTION_ID_RE.fullmatch(active_id)
        and target_id.startswith(f"{active_id}.")
        and replacement_id.startswith(f"{active_id}.")
    )
    if (
        not QUESTION_ID_RE.fullmatch(target_id)
        or not QUESTION_ID_RE.fullmatch(replacement_id)
        or (child_repair and not valid_child_scope)
        or (not child_repair and QUESTION_ID_RE.fullmatch(active_id) and target_id != active_id)
    ):
        return None, _issue(
            "correction_target_invalid", affected_id,
            f"Confirmed correction {correction_id} does not identify one valid question.",
        )
    question = _question(structure, target_id)
    if question is None:
        return None, _issue(
            "correction_evidence_unresolved", target_id,
            f"Confirmed correction {correction_id} could not resolve Question {target_id}.",
        )

    raw_question = patch.get("question_text")
    question_text = str(raw_question or "").strip()
    raw_lines = patch.get("solution_lines")
    if not isinstance(raw_lines, list) or any(not isinstance(line, str) for line in raw_lines):
        return None, _issue(
            "correction_content_invalid", target_id,
            f"Confirmed correction {correction_id} contains invalid memo working.",
        )
    solution_lines = [line.strip() for line in raw_lines if line.strip()]
    points = patch.get("mark_points")
    rename_requested = replacement_id != target_id
    if not question_text and not solution_lines and points is None and not rename_requested:
        return None, _issue(
            "correction_content_invalid", target_id,
            f"Confirmed correction {correction_id} contains no replacement content.",
        )
    if len(question_text) > 2000 or len(solution_lines) > 80 or any(len(line) > 1000 for line in solution_lines):
        return None, _issue(
            "correction_content_invalid", target_id,
            f"Confirmed correction {correction_id} exceeds the bounded content limits.",
        )

    mark_total = None
    calc_mode = None
    normalized_points: list[dict[str, Any]] = []
    trial = copy.deepcopy(structure)
    trial_question = _question(trial, target_id)
    if trial_question is None:
        return None, _issue(
            "correction_evidence_unresolved", target_id,
            f"Confirmed correction {correction_id} could not resolve Question {target_id}.",
        )
    if points is not None:
        mark_patch = dict(patch)
        # Reuse the strict mark-point validator on a temporary structure so the
        # content mutation remains atomic if the marking scheme is invalid.
        supplied_total = patch.get("printed_marks")
        if child_repair:
            try:
                supplied_total = int(supplied_total)
            except (TypeError, ValueError):
                supplied_total = 0
            if supplied_total < 1 or supplied_total > 999:
                return None, _issue(
                    "correction_mark_total_invalid", target_id,
                    f"Confirmed correction {correction_id} has an invalid child total.",
                )
            trial_question["printed_marks"] = supplied_total
        applied_marks, mark_issue = _apply_replace_mark_points(
            trial,
            correction_id=correction_id,
            category=category,
            affected_id=target_id,
            patch=mark_patch,
        )
        if mark_issue:
            return None, mark_issue
        trial_question = _question(trial, target_id)
        normalized_points = list((trial_question or {}).get("mark_points") or [])
        mark_total = (applied_marks or {}).get("mark_total")
        calc_mode = (applied_marks or {}).get("mark_calculation_mode")
        trial_question["teacher_marking_text"] = "\n".join(
            str(point.get("source") or "").strip()
            for point in normalized_points
            if str(point.get("source") or "").strip()
        )

    if rename_requested:
        if _question(trial, replacement_id) is not None:
            return None, _issue(
                "correction_target_conflict", replacement_id,
                f"Question identifier {replacement_id} already exists.",
            )
        trial_question["source_question_id"] = str(trial_question.get("source_question_id") or target_id)
        trial_question["question_id"] = replacement_id
        trial_question["path"] = [int(part) for part in replacement_id.split(".")]
        trial_question["depth"] = len(trial_question["path"])
        trial["questions"].sort(key=lambda item: (
            int(item.get("source_block_index", 10**9)),
            tuple(item.get("path") or (999,)),
        ))
    if question_text or solution_lines:
        trial_question["content_override"] = {
            "correction_id": correction_id,
            "question_text": question_text or None,
            "solution_lines": solution_lines,
        }
    trial_question["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "replace_item_content",
        **({"source_id": target_id} if rename_requested else {}),
    }
    _remove_exception(trial, category, affected_id)
    if points is not None:
        for related in ("mark_arithmetic_mismatch", "item_total_mismatch", "correction_mark_total_invalid"):
            _remove_exception(trial, related, target_id)
            if rename_requested:
                _remove_exception(trial, related, replacement_id)
    structure.clear()
    structure.update(trial)
    return {
        "correction_id": correction_id,
        "operation": "replace_item_content",
        "category": category,
        "affected_id": affected_id,
        "target_id": replacement_id,
        "source_id": target_id if rename_requested else None,
        "identifier_replaced": rename_requested,
        "question_text_replaced": bool(question_text),
        "solution_line_count": len(solution_lines),
        "mark_total": mark_total,
        "source_block_index": question.get("source_block_index"),
    }, None


def _apply_insert_missing_child_question(
    structure: dict[str, Any],
    normalized: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    parent_id = str(patch.get("parent_id") or affected_id or "").strip()
    question_id = str(patch.get("question_id") or patch.get("target_id") or "").strip()
    if (
        category != "question_total_mismatch"
        or not QUESTION_ID_RE.fullmatch(parent_id)
        or not QUESTION_ID_RE.fullmatch(question_id)
        or not question_id.startswith(f"{parent_id}.")
        or question_id == parent_id
        or not _exception_exists(structure, category, affected_id)
    ):
        return None, _issue(
            "correction_target_invalid", question_id or affected_id,
            f"Confirmed correction {correction_id} does not identify a missing child within the active parent review.",
        )
    if _question(structure, question_id) is not None:
        return None, _issue(
            "correction_target_conflict", question_id,
            f"Question identifier {question_id} already exists.",
        )
    try:
        printed_marks = int(patch.get("printed_marks"))
        source_index = patch.get("source_block_index")
        source_index = None if source_index is None else int(source_index)
    except (TypeError, ValueError):
        printed_marks, source_index = 0, None
    blocks = flatten_units(normalized) if normalized else []
    if not 1 <= printed_marks <= 999 or (source_index is not None and (source_index < 0 or (blocks and source_index >= len(blocks)))):
        return None, _issue(
            "correction_mark_total_invalid", question_id,
            f"Confirmed correction {correction_id} contains an invalid child total or source reference.",
        )

    trial = copy.deepcopy(structure)
    trial_question: dict[str, Any] = {
        "question_id": question_id,
        "source_question_id": None,
        "path": [int(part) for part in question_id.split(".")],
        "depth": len(question_id.split(".")),
        "context_only": False,
        "source_block_index": source_index,
        "source_preview": "Teacher-inserted missing subquestion",
        "printed_marks": printed_marks,
        "computed_shorthand_marks": 0,
        "mark_points": [],
        "mode": "additive",
    }
    trial.setdefault("questions", []).append(trial_question)
    applied_marks, mark_issue = _apply_replace_mark_points(
        trial,
        correction_id=correction_id,
        category=category,
        affected_id=question_id,
        patch=patch,
    )
    if mark_issue:
        return None, mark_issue
    trial_question = _question(trial, question_id) or trial_question
    trial_question["teacher_marking_text"] = "\n".join(
        str(point.get("source") or "").strip()
        for point in trial_question.get("mark_points", [])
        if str(point.get("source") or "").strip()
    )
    trial_question["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "insert_missing_child_question",
        "parent_id": parent_id,
    }
    trial["questions"].sort(key=lambda item: qtuple(str(item.get("question_id") or "")))
    _remove_exception(trial, category, affected_id)
    structure.clear()
    structure.update(trial)
    return {
        "correction_id": correction_id,
        "operation": "insert_missing_child_question",
        "category": category,
        "affected_id": affected_id,
        "target_id": question_id,
        "parent_id": parent_id,
        "mark_total": (applied_marks or {}).get("mark_total"),
        "source_block_index": source_index,
    }, None


def _composite_question_ids(value: str | None) -> list[str] | None:
    parts = [part.strip() for part in str(value or "").split(",")]
    if not 2 <= len(parts) <= 20:
        return None
    if any(not QUESTION_ID_RE.fullmatch(part) for part in parts):
        return None
    if len(set(parts)) != len(parts):
        return None
    return parts


def _apply_resolve_question_allocation_pairing(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    targets = _composite_question_ids(affected_id)
    if targets is None or not _exception_exists(structure, category, affected_id):
        return None, _issue(
            "correction_target_invalid", affected_id,
            f"Confirmed correction {correction_id} does not identify one active grouped allocation exception.",
        )

    raw_allocations = patch.get("allocations")
    if not isinstance(raw_allocations, list) or len(raw_allocations) != len(targets):
        return None, _issue(
            "correction_allocation_set_invalid", affected_id,
            f"Confirmed correction {correction_id} must allocate every grouped question exactly once.",
        )
    allocation_ids = [
        str(item.get("question_id") or "").strip() if isinstance(item, dict) else ""
        for item in raw_allocations
    ]
    if allocation_ids != targets or len(set(allocation_ids)) != len(targets):
        return None, _issue(
            "correction_allocation_set_invalid", affected_id,
            f"Confirmed correction {correction_id} has missing, duplicate, reordered, or extra question allocations.",
        )

    questions: dict[str, dict[str, Any]] = {}
    for target in targets:
        matches = [
            question for question in structure.get("questions", [])
            if str(question.get("question_id") or "") == target
        ]
        if len(matches) != 1 or matches[0].get("context_only"):
            return None, _issue(
                "correction_evidence_unresolved", target,
                f"Confirmed correction {correction_id} could not resolve one existing leaf Question {target}.",
            )
        questions[target] = matches[0]

    source_rows: set[int] = set()
    try:
        source_rows = {
            int(question.get("source_block_index", -1))
            for question in questions.values()
        }
    except (TypeError, ValueError):
        source_rows = set()
    if len(source_rows) != 1 or next(iter(source_rows)) < 0:
        return None, _issue(
            "correction_source_relationship_invalid", affected_id,
            f"Confirmed correction {correction_id} does not preserve one shared source row.",
        )

    validated: list[dict[str, Any]] = []
    for item in raw_allocations:
        target = str(item.get("question_id"))
        try:
            printed_marks = int(item.get("printed_marks"))
        except Exception:
            printed_marks = 0
        marking_text = str(item.get("marking_text") or "").strip()
        raw_points = item.get("mark_points")
        if not 1 <= printed_marks <= MAX_ASSESSMENT_TOTAL or not marking_text or len(marking_text) > 4000:
            return None, _issue(
                "correction_mark_total_invalid", target,
                f"Confirmed correction {correction_id} has an invalid total for Question {target}.",
            )
        if not isinstance(raw_points, list) or not raw_points or len(raw_points) > 100:
            return None, _issue(
                "correction_mark_scheme_invalid", target,
                f"Confirmed correction {correction_id} has no bounded mark scheme for Question {target}.",
            )

        points: list[dict[str, Any]] = []
        for raw_point in raw_points:
            if not isinstance(raw_point, dict):
                return None, _issue("correction_mark_scheme_invalid", target, f"Confirmed correction {correction_id} contains an invalid mark point.")
            try:
                count = int(raw_point.get("count"))
            except Exception:
                count = 0
            code = str(raw_point.get("code") or "").upper()
            descriptor = str(raw_point.get("descriptor") or "").strip()
            if not 1 <= count <= 10 or code not in MARK_CODES or not descriptor or len(descriptor) > 500:
                return None, _issue(
                    "correction_mark_scheme_invalid", target,
                    f"Confirmed correction {correction_id} contains an invalid mark point for Question {target}.",
                )
            points.append({
                "count": count,
                "code": code,
                "descriptor": descriptor,
                "semantic": semantic_for_code(code, descriptor),
                "source": f"{count}{code} {descriptor}",
                "notation": "teacher_confirmed",
            })

        parsed = parse_mark_points(marking_text)
        signature = lambda values: [
            (int(point.get("count") or 0), str(point.get("code") or "").upper(), str(point.get("descriptor") or "").strip())
            for point in values
        ]
        if signature(parsed) != signature(points):
            return None, _issue(
                "correction_mark_scheme_invalid", target,
                f"Confirmed correction {correction_id} has inconsistent marking text for Question {target}.",
            )
        computed, calculation_mode = effective_mark_total(points, marking_text)
        supplied_mode = str(item.get("mark_calculation_mode") or "")
        if computed != printed_marks or supplied_mode != calculation_mode:
            return None, _issue(
                "correction_mark_total_invalid", target,
                f"Confirmed correction {correction_id} does not reconcile the marking scheme and total for Question {target}.",
            )
        validated.append({
            "question_id": target,
            "printed_marks": printed_marks,
            "mark_points": points,
            "marking_text": marking_text,
            "mark_calculation_mode": calculation_mode,
        })

    # Commit only after every child has passed validation.
    trial = copy.deepcopy(structure)
    for allocation in validated:
        question = _question(trial, allocation["question_id"])
        assert question is not None
        question["printed_marks"] = allocation["printed_marks"]
        question["computed_shorthand_marks"] = allocation["printed_marks"]
        question["mark_points"] = allocation["mark_points"]
        question["teacher_marking_text"] = allocation["marking_text"]
        question["mark_calculation_mode"] = allocation["mark_calculation_mode"]
        question["correction_overlay"] = {
            "correction_id": correction_id,
            "operation": "resolve_question_allocation_pairing",
        }
    _remove_exception(trial, category, affected_id)
    _refresh_summary(trial)
    structure.clear()
    structure.update(trial)
    return {
        "correction_id": correction_id,
        "operation": "resolve_question_allocation_pairing",
        "category": category,
        "affected_id": affected_id,
        "target_ids": targets,
        "source_block_index": next(iter(source_rows)),
        "allocations": [
            {
                "question_id": item["question_id"],
                "printed_marks": item["printed_marks"],
                "mark_calculation_mode": item["mark_calculation_mode"],
            }
            for item in validated
        ],
    }, None


def _apply_insert_missing_major_question(
    structure: dict[str, Any],
    normalized: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    target_id = str(patch.get("target_id") or "").strip()
    if not re.fullmatch(r"\d{1,2}", target_id):
        return None, _issue(
            "correction_target_invalid",
            affected_id,
            f"Confirmed correction {correction_id} does not contain a valid major-question identifier.",
        )
    target_major = int(target_id)
    if _question(structure, target_id) is not None:
        return None, _issue(
            "correction_target_conflict",
            target_id,
            f"Question {target_id} already exists.",
        )

    affected_major = (
        qtuple(affected_id)[0] if QUESTION_ID_RE.fullmatch(affected_id) else None
    )
    if affected_major != target_major + 1:
        return None, _issue(
            "correction_target_invalid",
            affected_id,
            f"Confirmed correction {correction_id} is not a one-major numbering-gap repair.",
        )

    questions = [
        item
        for item in structure.get("questions", [])
        if not item.get("context_only")
    ]
    before = [
        item
        for item in questions
        if qtuple(str(item.get("question_id")))[0] < target_major
    ]
    after = [
        item
        for item in questions
        if qtuple(str(item.get("question_id")))[0] > target_major
    ]
    if not before or not after:
        return None, _issue(
            "correction_evidence_unresolved",
            target_id,
            f"Confirmed correction {correction_id} cannot bound the missing major question.",
        )
    lower = max(int(item.get("source_block_index", -1)) for item in before)
    upper = min(int(item.get("source_block_index", 10**9)) for item in after)
    if lower >= upper:
        return None, _issue(
            "correction_evidence_unresolved",
            target_id,
            f"Confirmed correction {correction_id} found an invalid source boundary.",
        )

    blocks = flatten_units(normalized)
    candidates: list[dict[str, Any]] = []
    subtotals = structure.get("subtotals") or []
    for index in range(lower + 1, min(upper, len(blocks))):
        block = blocks[index]
        if find_question_ids(str(block.get("source") or "")):
            continue
        if not str(block.get("source") or "").strip():
            continue
        points = parse_mark_points(str(block.get("marking") or ""))
        computed, calc_mode = effective_mark_total(
            points, str(block.get("marking") or "")
        )
        if computed <= 0:
            continue
        matching_subtotals = [
            subtotal
            for subtotal in subtotals
            if index <= int(subtotal.get("block_index", -1)) < upper
            and int(subtotal.get("value") or 0) == computed
        ]
        if not matching_subtotals:
            continue
        allocations = printed_allocations(str(block.get("allocation") or ""))
        candidates.append({
            "block_index": index,
            "block": block,
            "points": points,
            "computed": computed,
            "calc_mode": calc_mode,
            "printed_marks": allocations[0] if len(allocations) == 1 else None,
        })

    if len(candidates) != 1:
        return None, _issue(
            "correction_evidence_unresolved",
            target_id,
            (
                f"Confirmed correction {correction_id} could not resolve exactly "
                "one scored unlabelled source block inside the major-question gap."
            ),
        )

    candidate = candidates[0]
    question = {
        "question_id": target_id,
        "path": [target_major],
        "depth": 1,
        "context_only": False,
        "source_block_index": candidate["block_index"],
        "printed_marks": candidate["printed_marks"],
        "computed_shorthand_marks": candidate["computed"],
        "mark_calculation_mode": candidate["calc_mode"],
        "mark_points": candidate["points"],
        "source_preview": str(candidate["block"].get("source") or "")[:240],
        "source_unlabeled": True,
        "correction_overlay": {
            "correction_id": correction_id,
            "operation": "insert_missing_major_question",
        },
    }
    structure.setdefault("questions", []).append(question)
    structure["questions"].sort(
        key=lambda item: (
            int(item.get("source_block_index", 10**9)),
            tuple(item.get("path") or (999,)),
        )
    )
    _remove_exception(structure, category, affected_id)
    _remove_exception(structure, "unlabeled_mark_bearing_question", target_id)
    return {
        "correction_id": correction_id,
        "operation": "insert_missing_major_question",
        "category": category,
        "affected_id": affected_id,
        "target_id": target_id,
        "source_block_index": candidate["block_index"],
        "mark_total": candidate["computed"],
    }, None


def _major_for_subtotal(
    structure: dict[str, Any],
    subtotal: dict[str, Any],
) -> int | None:
    block_index = int(subtotal.get("block_index", -1))
    eligible = [
        (
            int(question.get("source_block_index", -1)),
            str(question.get("question_id") or ""),
        )
        for question in structure.get("questions", [])
        if int(question.get("source_block_index", -1)) <= block_index
    ]
    if not eligible:
        return None
    latest = max(position for position, _ in eligible)
    same = [qid for position, qid in eligible if position == latest]
    if not same:
        return None
    chosen = sorted(same, key=lambda value: (value.count("."), len(value)))[0]
    return qtuple(chosen)[0] if QUESTION_ID_RE.fullmatch(chosen) else None


def _apply_set_question_subtotal(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    target_id = str(patch.get("target_id") or "").strip()
    if not re.fullmatch(r"\d{1,2}", target_id):
        return None, _issue(
            "correction_target_invalid",
            None,
            f"Confirmed correction {correction_id} does not identify one major question.",
        )
    target_major = int(target_id)
    try:
        value = int(patch.get("subtotal"))
    except Exception:
        value = 0
    if not 1 <= value <= MAX_ASSESSMENT_TOTAL:
        return None, _issue(
            "correction_mark_total_invalid",
            target_id,
            f"Confirmed correction {correction_id} has an invalid question subtotal.",
        )

    major_question_rows = [
        question
        for question in structure.get("questions", [])
        if qtuple(str(question.get("question_id")))[0] == target_major
    ]
    if not major_question_rows:
        return None, _issue(
            "correction_evidence_unresolved",
            target_id,
            f"Confirmed correction {correction_id} cannot resolve Question {target_id}.",
        )
    source_index = min(
        int(question.get("source_block_index", 10**9))
        for question in major_question_rows
    )

    existing = [
        item
        for item in structure.get("subtotals", [])
        if _major_for_subtotal(structure, item) == target_major
    ]
    current_sum = sum(
        int(item.get("value") or 0) for item in structure.get("subtotals", [])
    )
    existing_sum = sum(int(item.get("value") or 0) for item in existing)
    new_sum = current_sum - existing_sum + value

    if existing:
        structure["subtotals"] = [
            item
            for item in structure.get("subtotals", [])
            if item not in existing
        ]
    structure.setdefault("subtotals", []).append({
        "value": value,
        "after_question": target_id,
        "block_index": source_index,
        "correction_overlay": {
            "correction_id": correction_id,
            "operation": "set_question_subtotal",
        },
    })
    structure["subtotals"].sort(
        key=lambda item: int(item.get("block_index", 10**9))
    )
    observed_total = (structure.get("summary") or {}).get("observed_document_total")
    if observed_total is None or new_sum == int(observed_total):
        _remove_exception(structure, category, None)
    else:
        for exception in structure.get("exceptions", []):
            if exception.get("category") == category and exception.get("affected_id") is None:
                exception["message"] = (
                    f"Detected question subtotals sum to {new_sum}, but the source "
                    f"TOTAL is {int(observed_total)}."
                )
    _refresh_summary(structure)
    return {
        "correction_id": correction_id,
        "operation": "set_question_subtotal",
        "category": category,
        "affected_id": None,
        "target_id": target_id,
        "subtotal": value,
        "source_block_index": source_index,
    }, None


def apply_phase7_5_patch(
    structure: dict[str, Any],
    normalized: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str | None,
    operation: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    affected = str(affected_id or "").strip()

    if (
        category == GROUPED_ALLOCATION_CATEGORY
        and operation == "resolve_question_allocation_pairing"
    ):
        applied, issue = _apply_resolve_question_allocation_pairing(
            structure,
            correction_id=correction_id,
            category=category,
            affected_id=affected_id,
            patch=patch,
        )
        return applied, issue, True

    if operation == "replace_item_content":
        applied, issue = _apply_replace_item_content(
            structure,
            correction_id=correction_id,
            category=category,
            affected_id=affected_id,
            patch=patch,
        )
        return applied, issue, True

    if operation == "insert_missing_child_question":
        applied, issue = _apply_insert_missing_child_question(
            structure,
            normalized,
            correction_id=correction_id,
            category=category,
            affected_id=affected_id,
            patch=patch,
        )
        return applied, issue, True

    if (
        category == "ambiguous_mark_semantics"
        and operation == "resolve_mark_semantic_conflict"
    ):
        applied, issue = _apply_resolve_mark_semantic_conflict(
            structure,
            correction_id=correction_id,
            category=category,
            affected_id=affected,
            patch=patch,
        )
        return applied, issue, True

    if category == "multiple_printed_allocations" and operation == "set_printed_marks":
        applied, issue = _apply_set_printed_marks(
            structure,
            normalized,
            correction_id=correction_id,
            category=category,
            affected_id=affected,
            patch=patch,
        )
        return applied, issue, True

    if category == "item_total_mismatch" and operation == "set_item_total_override":
        applied, issue = _apply_set_item_total_override(
            structure,
            correction_id=correction_id,
            category=category,
            affected_id=affected,
            patch=patch,
        )
        return applied, issue, True

    if (
        category in {
            "mark_arithmetic_mismatch",
            "item_total_mismatch",
            "correction_mark_total_invalid",
        }
        and operation == "replace_mark_points"
    ):
        applied, issue = _apply_replace_mark_points(
            structure,
            correction_id=correction_id,
            category=category,
            affected_id=affected,
            patch=patch,
        )
        return applied, issue, True

    if category == "major_question_gap" and operation == "insert_missing_major_question":
        applied, issue = _apply_insert_missing_major_question(
            structure,
            normalized,
            correction_id=correction_id,
            category=category,
            affected_id=affected,
            patch=patch,
        )
        return applied, issue, True

    if category == "subtotal_sum_unexpected" and operation == "set_question_subtotal":
        applied, issue = _apply_set_question_subtotal(
            structure,
            correction_id=correction_id,
            category=category,
            patch=patch,
        )
        return applied, issue, True

    return None, None, False


def _question_tokens_any(text: str) -> list[str]:
    result: list[str] = []
    for match in QUESTION_TOKEN_ANY_RE.finditer(text):
        value = match.group(1)
        if value not in result:
            result.append(value)
    return result


def phase7_5_deterministic_proposal(
    exception: dict[str, Any],
    evidence_text: str,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    category = str(exception.get("category") or "")
    affected = str(exception.get("affected_id") or "").strip()
    handled = category in PHASE7_5_REINTERPRET_CATEGORIES
    evidence: dict[str, Any] = {
        "phase7_5_category": category,
        "phase7_5_handled": handled,
    }
    content_proposal, content_display, content_evidence = _structured_content_proposal(
        exception, evidence_text
    )
    if content_evidence.get("structured_content_correction"):
        evidence.update(content_evidence)
        return content_proposal, content_display, evidence
    if not handled:
        return None, None, evidence

    # Never collapse a broader question/solution correction into a marks-only
    # patch. The structured editor can represent the complete teacher intent.
    if CONTENT_INTENT_RE.search(evidence_text):
        evidence["content_correction_requires_structured_editor"] = True
        return None, None, evidence

    if category == "multiple_printed_allocations":
        totals = sorted({int(value) for value in MARK_TOTAL_RE.findall(evidence_text)})
        evidence["candidate_mark_totals"] = totals
        if len(totals) != 1:
            return None, None, evidence
        total = totals[0]
        if not 1 <= total <= 20:
            return None, None, evidence
        proposal = {
            "schema_version": "1.0",
            "operation": "set_printed_marks",
            "category": category,
            "affected_id": exception.get("affected_id"),
            "printed_marks": total,
            "reinterpretation_method": "deterministic_teacher_mark_total",
        }
        return (
            proposal,
            f"Use the printed allocation of {total} marks for Question {affected}.",
            evidence,
        )

    if category in {
        "mark_arithmetic_mismatch",
        "item_total_mismatch",
        "correction_mark_total_invalid",
    }:
        if category == "item_total_mismatch":
            total_match = TEACHER_ITEM_TOTAL_RE.fullmatch(evidence_text.strip())
            bare_match = BARE_ITEM_TOTAL_RE.fullmatch(evidence_text.strip())
            natural_match = NATURAL_ITEM_TOTAL_RE.fullmatch(evidence_text.strip())
            corrected_match = CORRECTED_PAREN_TOTAL_RE.fullmatch(evidence_text.strip())
            raw_total = (
                total_match.group(1)
                if total_match
                else bare_match.group(1)
                if bare_match
                else natural_match.group(1)
                if natural_match
                else corrected_match.group(1)
                if corrected_match
                else None
            )
            if raw_total is not None:
                total = int(raw_total)
                evidence["teacher_item_total"] = total
                if 1 <= total <= 20:
                    proposal = {
                        "schema_version": "1.0",
                        "operation": "set_item_total_override",
                        "category": category,
                        "affected_id": exception.get("affected_id"),
                        "printed_marks": total,
                        "reinterpretation_method": "deterministic_teacher_item_total",
                    }
                    return (
                        proposal,
                        (
                            f"Override the printed item total for Question {affected} "
                            f"to {total} marks."
                        ),
                        evidence,
                    )

        normalised = re.sub(r"\s*[;|]\s*", "\n", evidence_text.strip())
        normalised = re.sub(
            r"\s+(?:and|,)\s+(?=\d+\s*(?:CA|M|A|F|S|R)\b)",
            "\n",
            normalised,
            flags=re.I,
        )
        points = parse_mark_points(normalised)
        total, calc_mode = effective_mark_total(points, normalised)
        evidence["parsed_mark_points"] = points
        evidence["parsed_mark_total"] = total
        evidence["parsed_mark_calculation_mode"] = calc_mode
        if not points or total <= 0:
            return None, None, evidence
        if any(
            int(item.get("count") or 0) <= 0
            or not str(item.get("descriptor") or "").strip()
            for item in points
        ):
            return None, None, evidence
        proposal = {
            "schema_version": "1.0",
            "operation": "replace_mark_points",
            "category": category,
            "affected_id": exception.get("affected_id"),
            "mark_points": points,
            "expected_total": total,
            "mark_calculation_mode": calc_mode,
            "reinterpretation_method": "deterministic_teacher_mark_scheme",
        }
        return (
            proposal,
            f"Use the teacher-confirmed {total}-mark scheme for Question {affected}.",
            evidence,
        )

    if category == "subtotal_sum_unexpected":
        match = SUBTOTAL_INSTRUCTION_RE.search(evidence_text)
        reversed_match = SUBTOTAL_FIRST_INSTRUCTION_RE.search(evidence_text)
        if not match and reversed_match:
            target, subtotal_text = reversed_match.group(2), reversed_match.group(1)
        elif match:
            target, subtotal_text = match.group(1), match.group(2)
        else:
            target = subtotal_text = None
        if target is None or subtotal_text is None:
            return None, None, evidence
        subtotal = int(subtotal_text)
        evidence["target_question"] = target
        evidence["subtotal"] = subtotal
        if not 1 <= subtotal <= MAX_ASSESSMENT_TOTAL:
            return None, None, evidence
        proposal = {
            "schema_version": "1.0",
            "operation": "set_question_subtotal",
            "category": category,
            "affected_id": exception.get("affected_id"),
            "target_id": target,
            "subtotal": subtotal,
            "reinterpretation_method": "deterministic_teacher_subtotal",
        }
        return (
            proposal,
            f"Record the teacher-confirmed observed subtotal of {subtotal} for Question {target}.",
            evidence,
        )

    if category == "major_question_gap":
        explicit = [match.group(1) for match in MAJOR_QUESTION_INSTRUCTION_RE.finditer(evidence_text)]
        bare = list(dict.fromkeys(explicit)) if explicit else [
            token for token in _question_tokens_any(evidence_text) if "." not in token
        ]
        evidence["candidate_major_question_ids"] = bare
        if len(bare) != 1:
            return None, None, evidence
        target = bare[0]
        proposal = {
            "schema_version": "1.0",
            "operation": "insert_missing_major_question",
            "category": category,
            "affected_id": exception.get("affected_id"),
            "target_id": target,
            "reinterpretation_method": "deterministic_major_numbering_text",
        }
        return (
            proposal,
            f"Interpret the scored unlabelled block in the numbering gap as Question {target}.",
            evidence,
        )

    if category in {
        "scored_major_precedes_subquestions",
        }:
        tokens = [token for token in _question_tokens_any(evidence_text) if "." in token]
        evidence["candidate_question_ids"] = tokens
        if len(tokens) != 1:
            return None, None, evidence
        target = tokens[0]
        if not affected or "." in affected:
            return None, None, evidence
        if target != affected + ".1":
            return None, None, evidence
        operation = "rename_question_identifier"
        display = f"Rename scored Question {affected} to Question {target}."
        proposal = {
            "schema_version": "1.0",
            "operation": operation,
            "category": category,
            "affected_id": exception.get("affected_id"),
            "target_id": target,
            "reinterpretation_method": "deterministic_numbering_text",
        }
        return proposal, display, evidence

    return None, None, evidence
