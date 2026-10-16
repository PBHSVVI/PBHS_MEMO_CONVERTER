from __future__ import annotations

from engine.src.memo_engine.canonical import (
    _dedupe_issues,
    _exception_record,
    build_canonical_memo,
)
from engine.src.memo_engine.structure import extract_structure, find_question_ids


def _normalized(*pages: str, total: int = 50) -> dict:
    return {
        "job_id": "phase8-structure-provenance",
        "source": {"sha256": "synthetic"},
        "content": {
            "kind": "pdf",
            "pages": [
                {"page": index, "effective_text": text}
                for index, text in enumerate(pages, start=1)
            ],
        },
    }


def test_line_leading_statistics_values_are_not_major_questions():
    text = """Page 2 of 5
QUESTION 2
2.1 Determine the median. (1)
68 ; 29 ; 31 ; 88 ; 100 ; 77
77 ; 68 ; 88 ; 100
[1]
TOTAL: 1
"""
    structure = extract_structure(_normalized(text, total=1))
    identifiers = [item["question_id"] for item in structure["questions"]]

    assert identifiers == ["2", "2.1"]
    assert not any(
        item["category"] == "major_question_gap"
        for item in structure["exceptions"]
    )


def test_true_headings_and_child_identifiers_still_parse():
    text = """INSTRUCTIONS:
1. Show all working.
2. Use a calculator.
QUESTION 7
7.1 Solve the equation. (2)
7.2 Give a reason. (1)
[3]
TOTAL: 3
"""
    assert find_question_ids(text) == ["7", "7.1", "7.2"]


def test_repeated_extraction_is_deduped_but_genuine_source_mismatch_remains():
    q4 = """Page 3 of 5
QUESTION 3
3.2 Estimate. (2)
3.3 Validate. (2)
[7]
QUESTION 4
4.1.1 First probability. (4)
4.1.2 Second probability. (1)
4.2 Show independence. (4)
[9]
"""
    repeated_tail = """Page 4 of 5
QUESTION 5
5.1 Draw the diagram. (8)
5.2 Use the diagram:
5.2.1 At least two. (2)
5.2.2 Exactly two. (2)
[12]
Page 5 of 5
QUESTION 6
All factorial answers must be simplified.
4.1 Arrange flags. (2)
4.2 Arrange COLLEGE:
4.2.1 No restrictions. (1)
4.2.2 C and O together. (3)
[6]
TOTAL: 34
"""
    structure = extract_structure(_normalized(q4, repeated_tail, repeated_tail, total=34))

    duplicates = {
        item["affected_id"]
        for item in structure["exceptions"]
        if item["category"] == "duplicate_question_identifier"
    }
    mismatches = {
        item["affected_id"]
        for item in structure["exceptions"]
        if item["category"] == "question_parent_heading_mismatch"
    }

    assert duplicates == {"4.2"}
    assert not duplicates.intersection({"5.1", "5.2", "5.2.1", "5.2.2"})
    assert {"4.1", "4.2", "4.2.1", "4.2.2"}.issubset(mismatches)
    assert structure["summary"]["subtotal_sum"] == 34
    assert [
        (item["value"], item["source_provenance"]["page"], item["resolved_major_question"])
        for item in structure["subtotals"]
    ] == [(7, 3, "3"), (9, 3, "4"), (12, 4, "5"), (6, 5, "6")]


def test_genuine_duplicate_identifier_on_same_source_page_remains_reviewable():
    text = """Page 1 of 1
QUESTION 2
2.1 First version. (1)
2.1 Second version. (1)
[2]
TOTAL: 2
"""
    structure = extract_structure(_normalized(text, total=2))
    duplicate = next(
        item for item in structure["exceptions"]
        if item["category"] == "duplicate_question_identifier"
    )

    assert duplicate["affected_id"] == "2.1"
    assert len(duplicate["suggestions"][0]["occurrences"]) == 2


def test_equal_subtotals_in_one_source_block_keep_distinct_owners():
    text = """Page 1 of 1
QUESTION 1
1.1 First item. (5)
[5]
QUESTION 2
2.1 Second item. (5)
[5]
TOTAL: 10
"""
    structure = extract_structure(_normalized(text, total=10))

    assert [
        (item["value"], item["resolved_major_question"])
        for item in structure["subtotals"]
    ] == [(5, "1"), (5, "2")]
    assert structure["summary"]["subtotal_sum"] == 10


def test_canonical_subtotals_use_resolved_heading_owner():
    text = """Page 3 of 5
QUESTION 4
4.1.1 First probability. (4)
4.1.2 Second probability. (1)
4.2 Show independence. (4)
[9]
Page 5 of 5
QUESTION 6
4.1 Arrange flags. (2)
4.2 Arrange letters:
4.2.1 No restrictions. (1)
4.2.2 Together. (3)
[6]
TOTAL: 15
"""
    normalized = _normalized(text, total=15)
    structure = extract_structure(normalized)
    canonical, _, _ = build_canonical_memo(
        {"id": "phase8-structure-provenance", "source_filename": "fixture.pdf", "source_mime": "application/pdf"},
        {"source": {"sha256": "synthetic", "detected_mime": "application/pdf"}},
        normalized,
        structure,
        {"exceptions": [], "interpreter_runs": [], "deterministic_results": [], "ai_results": []},
        b"",
    )

    q4 = next(item for item in canonical["questions"] if item["number"] == "4")
    q6 = next(item for item in canonical["questions"] if item["number"] == "6")
    assert q4["subtotal"]["observed"] == 9
    assert q6["subtotal"]["observed"] == 6
    exception_ids = [item["exception_id"] for item in canonical["exceptions"]]
    assert len(exception_ids) == len(set(exception_ids))


def test_duplicate_logical_exceptions_produce_one_stable_exception_id():
    issue = {
        "level": "red",
        "category": "duplicate_question_identifier",
        "affected_id": "4.2",
        "message": "Question identifier 4.2 appears more than once.",
    }
    records = [_exception_record(item) for item in _dedupe_issues([issue, issue.copy()])]

    assert len(records) == 1
    assert len({item["exception_id"] for item in records}) == 1
