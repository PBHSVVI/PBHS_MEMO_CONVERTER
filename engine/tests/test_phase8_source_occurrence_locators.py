from __future__ import annotations

import copy

from engine.src.memo_engine.corrections import apply_confirmed_corrections
from engine.src.memo_engine.structure import source_line_hash, source_locator_for_question


def _question(qid: str, block: int, page: int, heading: str, line: str) -> dict:
    return {
        "question_id": qid,
        "path": [int(part) for part in qid.split(".")],
        "depth": len(qid.split(".")),
        "source_block_index": block,
        "source_page": page,
        "source_heading_major": heading,
        "source_line": line,
        "source_line_hash": source_line_hash(line),
        "source_character_offset": 20,
        "printed_marks": 3,
        "computed_shorthand_marks": 3,
        "mark_points": [{"count": 3, "code": "A", "descriptor": "answer"}],
    }


def _normalized() -> dict:
    pages = [
        {"page": number, "effective_text": f"Page {number} of 5\nQUESTION {number}"}
        for number in range(1, 5)
    ]
    pages.append({
        "page": 5,
        "effective_text": "Page 5 of 5\nQUESTION 6\n4.1 First final answer\n4.2 Second final answer",
    })
    return {"content": {"pages": pages}}


def _correction(qid: str, target: str, old_block: int = 4, locator=None) -> dict:
    patch = {
        "operation": "rename_question_identifier",
        "category": "duplicate_question_identifier",
        "affected_id": qid,
        "target_id": target,
        "source_block_index": old_block,
    }
    if locator is not None:
        patch["source_locator"] = locator
    return {
        "id": f"rename-{qid}",
        "confirmation_status": "confirmed",
        "confirmed_at": f"2026-10-16T10:00:0{qid[-1]}Z",
        "proposed_patch": patch,
    }


def _structure() -> dict:
    return {
        "questions": [
            # The old numeric hint now points at this different physical 4.2;
            # page/heading/line compatibility must reject it.
            _question("4.2", 4, 3, "4", "4.2 Genuine Question 4 item"),
            _question("4.1", 3, 5, "6", "4.1 First final answer"),
            _question("4.2", 3, 5, "6", "4.2 Second final answer"),
            _question("4.2.1", 3, 5, "6", "4.2.1 Working"),
            _question("4.2.2", 3, 5, "6", "4.2.2 Answer"),
        ],
        "exceptions": [
            {"category": "duplicate_question_identifier", "affected_id": "4.1"},
            {"category": "duplicate_question_identifier", "affected_id": "4.2"},
            {"category": "question_parent_heading_mismatch", "affected_id": "4.1"},
            {"category": "question_parent_heading_mismatch", "affected_id": "4.2"},
        ],
        "summary": {},
    }


def test_legacy_block_locator_rebases_after_parser_deduplication_without_cross_parent_mapping():
    result, applied, issues = apply_confirmed_corrections(
        _structure(), _normalized(), [_correction("4.1", "6.1"), _correction("4.2", "6.2")]
    )
    assert issues == []
    assert [(item["affected_id"], item["target_id"]) for item in applied] == [("4.1", "6.1"), ("4.2", "6.2")]
    assert all(item["locator_resolution"]["method"] == "legacy_source_rebase" for item in applied)
    assert all(item["locator_resolution"]["original_source_block_index"] == 4 for item in applied)
    assert all(item["locator_resolution"]["resolved_source_block_index"] == 3 for item in applied)
    assert result["correction_overlay"]["history"][0]["locator_resolution"]["method"] == "legacy_source_rebase"
    rows = {(q["question_id"], q["source_page"], q["source_heading_major"]) for q in result["questions"]}
    assert ("4.2", 3, "4") in rows
    assert ("6.1", 5, "6") in rows
    assert ("6.2", 5, "6") in rows
    assert {q["question_id"] for q in result["questions"] if q["question_id"].startswith("4.2.")} == {"4.2.1", "4.2.2"}


def test_stable_locator_survives_block_shift_and_rejects_ambiguous_match():
    question = _question("4.2", 4, 5, "6", "4.2 Second final answer")
    locator = source_locator_for_question(question)
    structure = _structure()
    result, applied, issues = apply_confirmed_corrections(
        structure, _normalized(), [_correction("4.2", "6.2", locator=locator)]
    )
    assert issues == []
    assert applied[0]["locator_resolution"]["method"] == "stable_source_rebase"
    assert any(q["question_id"] == "6.2" and q["source_page"] == 5 for q in result["questions"])

    ambiguous = copy.deepcopy(structure)
    ambiguous["questions"].append(_question("4.2", 2, 5, "6", "4.2 Second final answer"))
    _, applied, issues = apply_confirmed_corrections(
        ambiguous, _normalized(), [_correction("4.2", "6.2", locator=locator)]
    )
    assert applied == []
    assert issues[0]["category"] == "correction_evidence_unresolved"


def test_exact_source_block_remains_the_first_resolution_method():
    structure = {"questions": [_question("4.1", 4, 5, "6", "4.1 First final answer")], "exceptions": [], "summary": {}}
    locator = source_locator_for_question(structure["questions"][0])
    _, applied, issues = apply_confirmed_corrections(
        structure, _normalized(), [_correction("4.1", "6.1", locator=locator)]
    )
    assert issues == []
    assert applied[0]["locator_resolution"]["method"] == "exact_source_block"
