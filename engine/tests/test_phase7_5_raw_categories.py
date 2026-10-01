from __future__ import annotations

from engine.src.memo_engine.phase7_5 import (
    apply_phase7_5_patch,
    enrich_structure_phase7_5,
    phase7_5_deterministic_proposal,
)
from engine.src.memo_engine.structure import extract_structure, parse_mark_points


def _cell(text: str) -> dict[str, str]:
    return {"text": text}


def _normalised_rows(rows: list[list[str]]) -> dict:
    return {
        "job_id": "job",
        "content": {
            "units": [{
                "type": "table",
                "rows": [[_cell(value) for value in row] for row in rows],
            }]
        },
    }


def _q(qid: str, block: int, *, printed=None, computed=None, points=None) -> dict:
    path = [int(part) for part in qid.split(".")]
    return {
        "question_id": qid,
        "path": path,
        "depth": len(path),
        "context_only": False,
        "source_block_index": block,
        "printed_marks": printed,
        "computed_shorthand_marks": computed,
        "mark_calculation_mode": "additive",
        "mark_points": list(points or []),
        "source_preview": qid,
    }


def test_enrichment_recovers_marking_only_question_5_2():
    normalised = _normalised_rows([
        ["5.1", "working", "1A log\n1A half base", "(2) (1)"],
        ["", "", "1 shape\n1A point", "(2)"],
        ["5.3", "working", "1M method\n1A answer", "(2)"],
    ])
    structure = {
        "questions": [_q("5.1", 0), _q("5.3", 2)],
        "subtotals": [],
        "unlabeled_mark_blocks": [],
        "exceptions": [{
            "level": "amber",
            "category": "possible_missing_question",
            "affected_id": "5.2",
            "message": "possible missing",
            "suggestions": [{"kind": "review_numbering", "candidate": "5.2"}],
        }],
        "summary": {},
    }

    enriched = enrich_structure_phase7_5(structure, normalised)

    assert enriched["unlabeled_mark_blocks"] == [{
        "block_index": 1,
        "printed_allocations": [2],
        "candidate": "5.2",
        "phase7_5_evidence": "marking_only_sequence_gap",
    }]
    categories = {(e["category"], e.get("affected_id")) for e in enriched["exceptions"]}
    assert ("possible_missing_question", "5.2") not in categories
    assert ("unlabeled_mark_bearing_question", "5.2") in categories


def test_enrichment_exposes_scored_major_8_as_numbering_review():
    normalised = _normalised_rows([
        ["8", "working", "1M method\n2A answer", "(3)"],
        ["8.2", "working", "1A answer", "(1)"],
    ])
    structure = {
        "questions": [
            _q("8", 0, printed=3, computed=3),
            _q("8.2", 1, printed=1, computed=1),
        ],
        "subtotals": [],
        "unlabeled_mark_blocks": [],
        "exceptions": [],
        "summary": {},
    }

    enriched = enrich_structure_phase7_5(structure, normalised)
    finding = next(
        e for e in enriched["exceptions"]
        if e["category"] == "scored_major_precedes_subquestions"
    )
    assert finding["affected_id"] == "8"
    assert finding["suggestions"] == [{"kind": "review_numbering", "candidate": "8.1"}]


def test_typed_5_1_mark_total_becomes_bounded_printed_mark_patch():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "multiple_printed_allocations", "affected_id": "5.1"},
        "Use 2 marks",
    )
    assert proposal["operation"] == "set_printed_marks"
    assert proposal["printed_marks"] == 2
    assert evidence["candidate_mark_totals"] == [2]
    assert "2 marks" in display


def test_typed_teacher_scheme_becomes_four_mark_replacement():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "mark_arithmetic_mismatch", "affected_id": "7.4"},
        "1M derivative; 1F factorisation; 1A critical values; 1A answer intervals",
    )
    assert proposal["operation"] == "replace_mark_points"
    assert proposal["expected_total"] == 4
    assert len(proposal["mark_points"]) == 4
    assert evidence["parsed_mark_total"] == 4
    assert "4-mark" in display


def test_typed_major_gap_becomes_insert_question_10():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "major_question_gap", "affected_id": "11.1.1"},
        "Question 10",
    )
    assert proposal["operation"] == "insert_missing_major_question"
    assert proposal["target_id"] == "10"
    assert evidence["candidate_major_question_ids"] == ["10"]
    assert "Question 10" in display


def test_set_printed_marks_requires_source_allocation_choice():
    normalised = _normalised_rows([
        ["5.1", "working", "1A log\n1A half base", "(2) (1)"],
    ])
    structure = {
        "questions": [_q("5.1", 0, printed=None, computed=2)],
        "exceptions": [{
            "level": "red", "category": "multiple_printed_allocations",
            "affected_id": "5.1", "message": "ambiguous", "suggestions": [],
        }],
        "subtotals": [],
        "summary": {},
    }
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-5-1",
        category="multiple_printed_allocations",
        affected_id="5.1",
        operation="set_printed_marks",
        patch={"printed_marks": 2},
    )
    assert handled is True
    assert issue is None
    assert applied["printed_marks"] == 2
    assert structure["questions"][0]["printed_marks"] == 2
    assert structure["exceptions"] == []


def test_replace_mark_points_repairs_7_4_without_touching_subtotal():
    old_points = [
        {"count": 1, "descriptor": "a"},
        {"count": 1, "descriptor": "b"},
        {"count": 1, "descriptor": "c"},
        {"count": 1, "descriptor": "d"},
        {"count": 1, "descriptor": "e"},
    ]
    structure = {
        "questions": [_q("7.4", 0, printed=4, computed=5, points=old_points)],
        "exceptions": [{
            "level": "amber", "category": "mark_arithmetic_mismatch",
            "affected_id": "7.4", "message": "5 vs 4", "suggestions": [],
        }],
        "subtotals": [{"value": 20, "block_index": 0}],
        "summary": {},
    }
    normalised = _normalised_rows([["7.4", "working", "old", "(4)"]])
    patch = phase7_5_deterministic_proposal(
        {"category": "mark_arithmetic_mismatch", "affected_id": "7.4"},
        "1M derivative; 1F factorisation; 1A critical values; 1A answer intervals",
    )[0]
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-7-4",
        category="mark_arithmetic_mismatch",
        affected_id="7.4",
        operation="replace_mark_points",
        patch=patch,
    )
    assert handled is True
    assert issue is None
    assert applied["mark_total"] == 4
    assert structure["questions"][0]["computed_shorthand_marks"] == 4
    assert structure["subtotals"] == [{"value": 20, "block_index": 0}]


def test_insert_missing_question_10_requires_unique_scored_unlabelled_block():
    normalised = _normalised_rows([
        ["9.4", "working", "1A answer", "(1)"],
        ["Quarter-circle problem", "working", "3M method\n1A substitution\n1A answer", "[5]"],
        ["11.1.1", "working", "2A all three correct\nOR\n1A two correct", "(2)"],
    ])
    structure = {
        "questions": [
            _q("9.4", 0, printed=1, computed=1),
            _q("11.1.1", 2, printed=2, computed=2),
        ],
        "subtotals": [{"value": 5, "block_index": 1}],
        "unlabeled_mark_blocks": [],
        "exceptions": [{
            "level": "red", "category": "major_question_gap",
            "affected_id": "11.1.1", "message": "9 -> 11", "suggestions": [],
        }],
        "summary": {},
    }
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-10",
        category="major_question_gap",
        affected_id="11.1.1",
        operation="insert_missing_major_question",
        patch={"target_id": "10"},
    )
    assert handled is True
    assert issue is None
    assert applied["target_id"] == "10"
    q10 = next(q for q in structure["questions"] if q["question_id"] == "10")
    assert q10["computed_shorthand_marks"] == 5
    assert q10["source_unlabeled"] is True
    assert not any(e["category"] == "major_question_gap" for e in structure["exceptions"])


def test_q3_subtotal_overlay_passes_when_ledger_reaches_source_total():
    # Existing observed ledger is 146 because Q3 [4] is absent.
    values = [23, 26, 14, 8, 13, 20, 13, 8, 5, 16]
    structure = {
        "questions": [_q(str(i), i, printed=None, computed=None) for i in range(1, 12)],
        "subtotals": [
            {"value": value, "block_index": block}
            for block, value in zip([1, 2, 4, 5, 6, 7, 8, 9, 10, 11], values)
        ],
        "exceptions": [{
            "level": "amber", "category": "subtotal_sum_unexpected",
            "affected_id": None, "message": "146", "suggestions": [],
        }],
        "summary": {"observed_document_total": 150},
    }
    normalised = _normalised_rows([[str(i), "", "", ""] for i in range(1, 12)])
    proposal = phase7_5_deterministic_proposal(
        {"category": "subtotal_sum_unexpected", "affected_id": None},
        "Q3 subtotal 4",
    )[0]
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-q3",
        category="subtotal_sum_unexpected",
        affected_id=None,
        operation="set_question_subtotal",
        patch=proposal,
    )
    assert handled is True
    assert issue is None
    assert applied["subtotal"] == 4
    assert sum(item["value"] for item in structure["subtotals"]) == 150
    assert not any(e["category"] == "subtotal_sum_unexpected" for e in structure["exceptions"])

def test_item_total_teacher_override_accepts_plain_language():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.1.1"},
        "award 3 marks",
    )
    assert proposal["operation"] == "set_item_total_override"
    assert proposal["printed_marks"] == 3
    assert proposal["reinterpretation_method"] == "deterministic_teacher_item_total"
    assert evidence["teacher_item_total"] == 3
    assert "3 marks" in display


def test_item_total_teacher_override_accepts_parenthesised_total():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.1.1"},
        "(3)",
    )
    assert proposal["operation"] == "set_item_total_override"
    assert proposal["printed_marks"] == 3
    assert evidence["teacher_item_total"] == 3
    assert "3 marks" in display


def test_item_total_override_reconciles_printed_two_to_computed_three():
    normalised = _normalised_rows([
        ["11.1.1", "working", "1A one\\n1A two\\n1A three", "(2)"],
    ])
    structure = {
        "questions": [_q("11.1.1", 0, printed=2, computed=3, points=[
            {"count": 1, "descriptor": "one"},
            {"count": 1, "descriptor": "two"},
            {"count": 1, "descriptor": "three"},
        ])],
        "exceptions": [{
            "level": "red",
            "category": "item_total_mismatch",
            "affected_id": "11.1.1",
            "message": "prints 2 but computes 3",
            "suggestions": [],
        }],
        "subtotals": [],
        "summary": {},
    }
    patch = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.1.1"},
        "award 3 marks",
    )[0]
    applied, issue, handled = apply_phase7_5_patch(
        structure,
        normalised,
        correction_id="corr-11-1-1",
        category="item_total_mismatch",
        affected_id="11.1.1",
        operation=patch["operation"],
        patch=patch,
    )
    assert handled is True
    assert issue is None
    assert applied["source_printed_marks"] == 2
    assert applied["printed_marks"] == 3
    assert structure["questions"][0]["printed_marks"] == 3
    assert structure["questions"][0]["computed_shorthand_marks"] == 3
    assert structure["exceptions"] == []

def test_conditional_accuracy_correction_is_max_not_sum():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {
            "category": "correction_mark_total_invalid",
            "affected_id": "11.1.1",
        },
        "2A for 3 correct answers; 1A for 2 correct answers.",
    )
    assert proposal["operation"] == "replace_mark_points"
    assert proposal["expected_total"] == 2
    assert proposal["mark_calculation_mode"] == "conditional_accuracy"
    assert evidence["parsed_mark_total"] == 2
    assert evidence["parsed_mark_calculation_mode"] == "conditional_accuracy"
    assert "2-mark" in display


def test_conditional_accuracy_overlay_replaces_bad_additive_total():
    normalised = _normalised_rows([
        ["11.1.1", "working", "2A for 3 correct answers\\n1A for 2 correct answers", "(2)"],
    ])
    structure = {
        "questions": [_q(
            "11.1.1", 0, printed=2, computed=3,
            points=[
                {"count": 2, "code": "A", "descriptor": "for 3 correct answers"},
                {"count": 1, "code": "A", "descriptor": "for 2 correct answers"},
            ],
        )],
        "exceptions": [{
            "level": "red",
            "category": "correction_mark_total_invalid",
            "affected_id": "11.1.1",
            "message": "teacher total conflict",
            "suggestions": [],
        }],
        "subtotals": [],
        "summary": {},
    }
    patch = phase7_5_deterministic_proposal(
        {
            "category": "correction_mark_total_invalid",
            "affected_id": "11.1.1",
        },
        "2A for 3 correct answers; 1A for 2 correct answers.",
    )[0]
    applied, issue, handled = apply_phase7_5_patch(
        structure,
        normalised,
        correction_id="corr-conditional",
        category="correction_mark_total_invalid",
        affected_id="11.1.1",
        operation="replace_mark_points",
        patch=patch,
    )
    assert handled is True
    assert issue is None
    assert applied["mark_total"] == 2
    assert applied["mark_calculation_mode"] == "conditional_accuracy"
    assert structure["questions"][0]["computed_shorthand_marks"] == 2
    assert structure["questions"][0]["mark_calculation_mode"] == "conditional_accuracy"


def test_structured_content_correction_replaces_question_working_and_marks():
    normalised = _normalised_rows([
        ["11.2.1", "wrong working", "old marks", "(4)"],
    ])
    structure = {
        "questions": [_q("11.2.1", 0, printed=4, computed=0, points=[])],
        "exceptions": [{
            "level": "red", "category": "item_total_mismatch",
            "affected_id": "11.2.1", "message": "0 vs 4", "suggestions": [],
        }],
        "subtotals": [],
        "summary": {},
    }
    teacher_text = """[[PBHS_CONTENT_CORRECTION_V1]]
TARGET: 11.2.1
QUESTION:
Show that the number of possibilities is 2 786 918 400.
ANSWER:
4! × 24 × (10 × 9 × 8 × 7) × 2! × 6!
= 2 786 918 400
MARKING:
3A calculation
1A answer
[[END_PBHS_CONTENT_CORRECTION_V1]]"""
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.2.1"},
        teacher_text,
    )
    assert proposal["operation"] == "replace_item_content"
    assert proposal["expected_total"] == 4
    assert evidence["structured_content_correction"] is True
    assert "Question 11.2.1" in display

    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-content",
        category="item_total_mismatch",
        affected_id="11.2.1",
        operation="replace_item_content",
        patch=proposal,
    )
    assert handled is True
    assert issue is None
    assert applied["solution_line_count"] == 2
    question = structure["questions"][0]
    assert question["content_override"]["question_text"].startswith("Show that")
    assert question["computed_shorthand_marks"] == 4
    assert question["teacher_marking_text"] == "3A calculation\n1A answer"
    assert structure["exceptions"] == []


def test_structured_content_correction_fails_closed_on_wrong_target():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.2.1"},
        """[[PBHS_CONTENT_CORRECTION_V1]]
TARGET: invalid
QUESTION:
Correct text
ANSWER:
Correct working
MARKING:

[[END_PBHS_CONTENT_CORRECTION_V1]]""",
    )
    assert proposal is None
    assert display is None
    assert evidence["structured_content_correction"] is True


def test_broader_content_intent_never_collapses_to_marks_only():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.2.1"},
        (
            "The question and the answer box are incorrect. "
            "The value in the question should be 2786918400. "
            "The answer box should read 4! x 24. "
            "Marking is awarded: 3A for calculation and 1A for answer."
        ),
    )
    assert proposal is None
    assert display is None
    assert evidence["content_correction_requires_structured_editor"] is True


def test_mark_scheme_accepts_and_as_separator_without_special_syntax():
    proposal, _, _ = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.2.1"},
        "3A for calculation and 1A for answer",
    )
    assert proposal["operation"] == "replace_mark_points"
    assert proposal["expected_total"] == 4
    assert len(proposal["mark_points"]) == 2


def _allocation(question_id: str, total: int, text: str) -> dict:
    from engine.src.memo_engine.structure import effective_mark_total

    points = parse_mark_points(text)
    computed, mode = effective_mark_total(points, text)
    assert computed == total
    return {
        "question_id": question_id,
        "printed_marks": total,
        "marking_text": text,
        "mark_points": points,
        "mark_calculation_mode": mode,
    }


def _grouped_allocation_fixture(*, split_source: bool = False) -> tuple[dict, dict, list[dict]]:
    ids = ["4.1", "4.2", "4.3", "4.4", "4.5"]
    structure = {
        "questions": [
            _q(qid, 1 if split_source and qid == "4.5" else 0)
            for qid in ids
        ],
        "subtotals": [],
        "exceptions": [{
            "level": "amber",
            "category": "question_allocation_pairing_ambiguous",
            "affected_id": ",".join(ids),
            "message": "shared source row",
            "suggestions": [],
        }],
        "summary": {},
    }
    normalised = _normalised_rows([["4.1 4.2 4.3 4.4 4.5", "shared", "marks", ""]])
    allocations = [
        _allocation("4.1", 2, "1M method\n1A answer"),
        _allocation("4.2", 3, "1M setup\n2A answer"),
        _allocation("4.3", 2, "1M method\n1A answer\nOR\n2A alternative answer"),
        _allocation("4.4", 4, "2M method\n2A answer"),
        _allocation("4.5", 3, "1M setup\n2A result"),
    ]
    return structure, normalised, allocations


def test_grouped_allocation_pairing_applies_five_questions_atomically():
    structure, normalised, allocations = _grouped_allocation_fixture()
    affected = "4.1,4.2,4.3,4.4,4.5"
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-grouped",
        category="question_allocation_pairing_ambiguous",
        affected_id=affected,
        operation="resolve_question_allocation_pairing",
        patch={"allocations": allocations},
    )
    assert handled is True
    assert issue is None
    assert applied["target_ids"] == affected.split(",")
    assert sum(q["printed_marks"] for q in structure["questions"]) == 14
    assert next(q for q in structure["questions"] if q["question_id"] == "4.3")["mark_calculation_mode"] == "alternative_max"
    assert structure["exceptions"] == []


def test_grouped_allocation_pairing_is_atomic_when_one_child_is_invalid():
    from copy import deepcopy

    structure, normalised, allocations = _grouped_allocation_fixture()
    before = deepcopy(structure)
    allocations[2]["printed_marks"] = 3
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-grouped-invalid",
        category="question_allocation_pairing_ambiguous",
        affected_id="4.1,4.2,4.3,4.4,4.5",
        operation="resolve_question_allocation_pairing",
        patch={"allocations": allocations},
    )
    assert handled is True
    assert applied is None
    assert issue["category"] == "correction_mark_total_invalid"
    assert structure == before


def test_grouped_allocation_pairing_requires_exact_target_set():
    from copy import deepcopy

    for altered in ("missing", "duplicate", "extra"):
        structure, normalised, allocations = _grouped_allocation_fixture()
        before = deepcopy(structure)
        if altered == "missing":
            allocations = allocations[:-1]
        elif altered == "duplicate":
            allocations[1]["question_id"] = "4.1"
        else:
            allocations.append(_allocation("4.6", 1, "1A answer"))
        applied, issue, handled = apply_phase7_5_patch(
            structure, normalised,
            correction_id=f"corr-{altered}",
            category="question_allocation_pairing_ambiguous",
            affected_id="4.1,4.2,4.3,4.4,4.5",
            operation="resolve_question_allocation_pairing",
            patch={"allocations": allocations},
        )
        assert handled is True
        assert applied is None
        assert issue["category"] == "correction_allocation_set_invalid"
        assert structure == before


def test_grouped_allocation_pairing_requires_one_shared_source_row():
    from copy import deepcopy

    structure, normalised, allocations = _grouped_allocation_fixture(split_source=True)
    before = deepcopy(structure)
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-source",
        category="question_allocation_pairing_ambiguous",
        affected_id="4.1,4.2,4.3,4.4,4.5",
        operation="resolve_question_allocation_pairing",
        patch={"allocations": allocations},
    )
    assert handled is True
    assert applied is None
    assert issue["category"] == "correction_source_relationship_invalid"
    assert structure == before


def test_content_replacement_cannot_clear_grouped_allocation_exception():
    structure, normalised, _ = _grouped_allocation_fixture()
    applied, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-content",
        category="question_allocation_pairing_ambiguous",
        affected_id="4.1,4.2,4.3,4.4,4.5",
        operation="replace_item_content",
        patch={"target_id": "4.1", "question_text": "replacement"},
    )
    assert handled is True
    assert applied is None
    assert issue["category"] == "correction_operation_invalid"
    assert len(structure["exceptions"]) == 1


def test_source_defined_document_totals_are_not_forced_to_one_benchmark():
    for total in (40, 75, 100, 150):
        structure = extract_structure(_normalised_rows([[f"TOTAL {total}"]]))
        assert structure["summary"]["observed_document_total"] == total
        assert not any(item["category"] == "subtotal_sum_unexpected" for item in structure["exceptions"])


def test_missing_source_total_is_not_fabricated():
    structure = extract_structure(_normalised_rows([["QUESTION 1", "working", "1A answer", "(1)"]]))
    assert structure["summary"]["observed_document_total"] is None


def test_subtotal_corrections_can_reconcile_sequentially_to_source_total():
    structure = {
        "questions": [_q("1", 0), _q("2", 1), _q("3", 2)],
        "subtotals": [{"question": 1, "value": 70, "block_index": 0}],
        "exceptions": [{
            "level": "amber", "category": "subtotal_sum_unexpected",
            "affected_id": None, "message": "70 vs 100", "suggestions": [],
        }],
        "summary": {"observed_document_total": 100},
    }
    normalised = _normalised_rows([["1"], ["2"], ["3"], ["TOTAL 100"]])
    first, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-q2", category="subtotal_sum_unexpected",
        affected_id=None, operation="set_question_subtotal",
        patch={"target_id": "2", "subtotal": 10},
    )
    assert handled and issue is None and structure["summary"]["subtotal_sum"] == 80
    assert any(item["category"] == "subtotal_sum_unexpected" for item in structure["exceptions"])
    second, issue, handled = apply_phase7_5_patch(
        structure, normalised,
        correction_id="corr-q3", category="subtotal_sum_unexpected",
        affected_id=None, operation="set_question_subtotal",
        patch={"target_id": "3", "subtotal": 20},
    )
    assert handled and issue is None and structure["summary"]["subtotal_sum"] == 100
    assert not any(item["category"] == "subtotal_sum_unexpected" for item in structure["exceptions"])
