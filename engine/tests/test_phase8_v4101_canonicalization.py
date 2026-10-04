from __future__ import annotations

from engine.src.memo_engine.canonical import build_canonical_memo, safe_source_block_index


SIX_MARK_POINTS = [
    {"count": 1, "code": "A", "semantic": "accuracy", "descriptor": "maximum value 2 f(x)", "source": "1A maximum value 2 f(x)"},
    {"count": 1, "code": "A", "semantic": "accuracy", "descriptor": "shape f(x)", "source": "1A shape f(x)"},
    {"count": 1, "code": "M", "semantic": "method", "descriptor": "x-intercepts f(x)", "source": "1M x-intercepts f(x)"},
    {"count": 1, "code": "M", "semantic": "method", "descriptor": "asymptotes g(x)", "source": "1M asymptotes g(x)"},
    {"count": 1, "code": "A", "semantic": "accuracy", "descriptor": "shape g(x)", "source": "1A shape g(x)"},
    {"count": 1, "code": "M", "semantic": "method", "descriptor": "x-intercepts g(x)", "source": "1M x-intercepts g(x)"},
]


def _question(qid: str, marks: int, source_block_index: int | str | None) -> dict:
    return {
        "question_id": qid,
        "path": [int(part) for part in qid.split(".")],
        "depth": len(qid.split(".")),
        "source_block_index": source_block_index,
        "printed_marks": marks,
        "computed_shorthand_marks": marks,
        "mark_calculation_mode": "additive",
        "mark_points": [{
            "count": marks,
            "code": "A",
            "semantic": "accuracy",
            "descriptor": f"Question {qid} answer",
            "source": f"{marks}A Question {qid} answer",
        }],
    }


def _build(structure: dict, pages: list[str]):
    return build_canonical_memo(
        {
            "id": "pilot-job",
            "source_filename": "pilot.pdf",
            "source_mime": "application/pdf",
        },
        {"source": {"sha256": "a" * 64, "detected_mime": "application/pdf"}},
        {
            "job_id": "pilot-job",
            "content": {
                "pages": [
                    {"page": index + 1, "effective_text": text}
                    for index, text in enumerate(pages)
                ]
            },
        },
        structure,
        {"exceptions": [], "interpreter_runs": [], "deterministic_results": [], "ai_results": []},
        b"",
    )


def _find_item(items: list[dict], number: str) -> dict:
    for item in items:
        if item["number"] == number:
            return item
        found = _find_item(item.get("children", []), number)
        if found:
            return found
    return {}


def test_source_block_index_normalization_is_bounded():
    assert safe_source_block_index(3) == 3
    assert safe_source_block_index(" 3 ") == 3
    assert safe_source_block_index(None) is None
    assert safe_source_block_index(True) is None
    assert safe_source_block_index("3.5") is None
    assert safe_source_block_index("not-a-position") is None


def test_teacher_inserted_child_without_source_block_canonicalizes_q6_to_20():
    inserted = _question("6.1", 6, None)
    inserted.update({
        "teacher_marking_text": "\n".join(point["source"] for point in SIX_MARK_POINTS),
        "mark_points": SIX_MARK_POINTS,
        "correction_overlay": {
            "correction_id": "e8624375-b844-4990-8d24-30e4fb0b29e9",
            "operation": "insert_missing_child_question",
        },
    })
    structure = {
        "questions": [
            inserted,
            _question("6.2", 8, 0),
            _question("6.3", 4, "1"),
            _question("6.4", 2, 2),
        ],
        "subtotals": [{"block_index": 3, "value": 20}],
        "exceptions": [],
    }

    memo, validation, issues = _build(
        structure,
        ["6.2 source working", "6.3 source working", "6.4 source working", "QUESTION 6 [20]\nTOTAL: 20"],
    )

    question = memo["questions"][0]
    child = _find_item(question["items"], "6.1")
    assert child["marks"] == {"observed": 6, "computed": 6, "status": "match"}
    assert question["subtotal"] == {"observed": 20, "computed": 20, "status": "match"}
    assert len(child["alternatives"][0]["marking_points"]) == 6
    assert child["source_refs"] == []
    assert child["correction_origin"] == {
        **inserted["correction_overlay"],
        "source_block_index": None,
    }
    assert validation["passed"] is True
    assert issues == []


def test_source_backed_and_renamed_questions_keep_source_segmentation():
    normal = _question("2.1", 1, "0")
    renamed = _question("3.1.1", 2, 1)
    renamed["source_question_id"] = "3.1"
    structure = {
        "questions": [normal, renamed],
        "subtotals": [
            {"block_index": 0, "value": 1},
            {"block_index": 2, "value": 2},
        ],
        "exceptions": [],
    }

    memo, _, _ = _build(
        structure,
        ["2.1 Normal source working", "3.1 Original source working", "QUESTION 3 [2]\nTOTAL: 3"],
    )

    q2 = next(question for question in memo["questions"] if question["number"] == "2")
    q3 = next(question for question in memo["questions"] if question["number"] == "3")
    normal_item = _find_item(q2["items"], "2.1")
    renamed_item = _find_item(q3["items"], "3.1.1")
    assert normal_item["alternatives"][0]["blocks"][0]["source_refs"]
    assert renamed_item["alternatives"][0]["blocks"][0]["source_refs"]
    assert "Original source working" in renamed_item["alternatives"][0]["blocks"][0]["text"]
