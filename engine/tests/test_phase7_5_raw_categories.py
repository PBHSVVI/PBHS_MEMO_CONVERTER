from __future__ import annotations

from engine.src.memo_engine.phase7_5 import (
    apply_phase7_5_patch,
    enrich_structure_phase7_5,
    phase7_5_deterministic_proposal,
)


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


def test_q3_subtotal_overlay_only_passes_when_observed_ledger_reaches_150():
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
        "summary": {},
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
