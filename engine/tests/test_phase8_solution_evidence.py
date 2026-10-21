from __future__ import annotations

from copy import deepcopy

import pytest

from engine.src.memo_engine.canonical import (
    _content_segments,
    _qid_segments,
    build_canonical_memo,
    validate_canonical,
)


def _question(
    question_id: str,
    *,
    source_question_id: str | None = None,
    visual_text: str | None = None,
) -> dict:
    result = {
        "question_id": question_id,
        "source_question_id": source_question_id or question_id,
        "path": [int(part) for part in question_id.split(".")],
        "depth": len(question_id.split(".")),
        "context_only": False,
        "source_block_index": 0,
        "source_page": 1,
        "source_character_offset": 0,
        "printed_marks": 1,
        "computed_shorthand_marks": 1,
        "mark_calculation_mode": "additive",
        "mark_points": [{
            "count": 1,
            "code": "A",
            "descriptor": "answer",
            "notation": "shorthand",
        }],
        "source_preview": "synthetic source evidence",
    }
    if visual_text is not None:
        result["visual_solution_segments"] = [{
            "text": visual_text,
            "raw_transcription": visual_text,
            "canonical_latex": None,
            "confidence": 0.95,
            "rendered_asset_ref": "internal/visual/synthetic.png",
            "source_ref": {"file_id": "source_1", "page": 1},
        }]
        result["visual_evidence"] = [{
            "kind": "answer_working",
            "confidence": 0.95,
            "rendered_asset_ref": "internal/visual/synthetic.png",
        }]
    return result


def _build(page_text: str, question: dict):
    normalized = {
        "job_id": "synthetic-solution-evidence",
        "source": {"sha256": "synthetic", "detected_kind": "pdf"},
        "content": {
            "kind": "pdf",
            "pages": [{"page": 1, "effective_text": page_text}],
        },
    }
    structure = {
        "job_id": normalized["job_id"],
        "questions": [question],
        "subtotals": [],
        "exceptions": [],
    }
    semantic = {
        "phase": "phase4_semantics",
        "deterministic_results": [],
        "ai_results": [],
        "exceptions": [],
        "interpreter_runs": [],
    }
    job = {
        "id": normalized["job_id"],
        "source_filename": "synthetic.pdf",
        "source_mime": "application/pdf",
    }
    ingestion = {
        "source": {
            "sha256": "synthetic",
            "detected_kind": "pdf",
            "detected_mime": "application/pdf",
            "size_bytes": 1,
        }
    }
    return build_canonical_memo(
        job, ingestion, normalized, structure, semantic, b"%PDF-synthetic"
    )


def _item(canonical: dict) -> dict:
    def walk(items):
        for item in items:
            if item.get("alternatives"):
                return item
            found = walk(item.get("children", []))
            if found is not None:
                return found
        return None

    result = walk(canonical["questions"][0]["items"])
    assert result is not None
    return result


@pytest.mark.parametrize(
    ("question_id", "source_question_id", "prompt"),
    [
        ("1.2", "1.2", "Determine the probability of success. (1)"),
        ("4.2", "4.2", "Calculate whether the events are independent. (1)"),
        ("6.2.1", "4.2.1", "In how many ways can the letters be arranged? (1)"),
    ],
)
def test_prompt_only_scored_leaf_requires_review_and_preserves_provenance(
    question_id: str, source_question_id: str, prompt: str
):
    page = f"QUESTION {source_question_id.split('.')[0]}\n{source_question_id} {prompt}\nTOTAL: 1"
    canonical, validation, _ = _build(
        page,
        _question(question_id, source_question_id=source_question_id),
    )

    item = _item(canonical)
    assert item["alternatives"][0]["blocks"] == []
    assert item["alternatives"][0]["marking_points"]
    assert item["source_prompt"] == prompt
    assert item["solution_evidence"]["source_question_id"] == source_question_id
    assert item["solution_evidence"]["source_block_index"] == 0
    assert item["solution_evidence"]["rejected_content_roles"] == ["question_prompt"]
    assert item["marks"]["computed"] == 1
    assert "leaf_solution_missing" in validation["error_codes"]
    assert canonical["status"] != "render_ready"
    exception = next(
        entry for entry in canonical["exceptions"]
        if entry["category"] == "leaf_solution_missing"
    )
    provenance = exception["suggestions"][0]
    assert provenance["source_question_id"] == source_question_id
    assert provenance["source_block_index"] == 0
    assert provenance["source_page"] == 1
    assert provenance["rejected_question_prompt"] is True
    assert provenance["reason"] == "solution_evidence_missing"


@pytest.mark.parametrize("heading", ["QUESTION 4", "Question 4", "QUESTION 10"])
def test_major_heading_terminates_previous_item_span(heading: str):
    record = {
        "paragraphs": [{
            "text": f"3.3 Would this be a valid estimate? (2) [7]\n{heading}\n4.1 Next item",
            "source_ref": {"file_id": "source_1", "page": 3},
            "content_role": "other",
        }]
    }
    segmented = _qid_segments(record, ["3.3", "4.1"])
    previous = " ".join(segment["text"] for segment in segmented["3.3"])
    assert heading not in previous
    assert "Next item" in " ".join(segment["text"] for segment in segmented["4.1"])


def test_ordinary_numeric_item_terminates_previous_span():
    record = {
        "paragraphs": [{
            "text": "3.3 First content\n3.4 Second content",
            "source_ref": {"file_id": "source_1", "page": 3},
            "content_role": "other",
        }]
    }
    segmented = _qid_segments(record, ["3.3", "3.4"])
    assert "Second content" not in segmented["3.3"][0]["text"]
    assert "Second content" in segmented["3.4"][0]["text"]


def test_heading_like_phrase_inside_prose_does_not_split():
    record = {
        "paragraphs": [{
            "text": "3.3 Question 4 illustrates the method used in this answer.",
            "source_ref": {"file_id": "source_1", "page": 3},
            "content_role": "solution_working",
        }]
    }
    segmented = _qid_segments(record, ["3.3"])
    assert "Question 4 illustrates" in segmented["3.3"][0]["text"]


@pytest.mark.parametrize(
    "question_id,answer",
    [
        ("2.4", "(35.9 - 19.9; 35.9 + 19.9) = (16; 55.8)"),
        ("3.1", "y = 0.77x + 6.71"),
        ("3.2", "y = 0.77(14) + 6.71 = 17.49"),
        ("6.1", "8 x 7 x 6 x 5 x 4 = 6720"),
    ],
)
def test_accepted_visual_solution_remains_usable(question_id: str, answer: str):
    canonical, validation, _ = _build(
        f"{question_id} Calculate the answer. (1)\nTOTAL: 1",
        _question(question_id, visual_text=answer),
    )
    item = _item(canonical)
    assert item["alternatives"][0]["blocks"]
    assert "leaf_solution_missing" not in validation["error_codes"]


def test_typed_pdf_math_solution_remains_eligible():
    canonical, validation, _ = _build(
        "QUESTION 1\n1.1\nx = 2 + 3 = 5\nTOTAL: 1",
        _question("1.1"),
    )
    item = _item(canonical)
    assert item["alternatives"][0]["blocks"]
    assert item["alternatives"][0]["blocks"][0]["source_content_role"] == "solution_working"
    assert "leaf_solution_missing" not in validation["error_codes"]


def test_teacher_question_text_is_not_promoted_but_solution_lines_are():
    source = [{
        "text": "Determine x. (1)",
        "content_role": "question_prompt",
        "source_ref": {"file_id": "source_1", "page": 1},
    }]
    selected = _content_segments({
        "content_override": {
            "correction_id": "teacher-correction",
            "question_text": "Corrected question wording",
            "solution_lines": ["x = 3"],
        }
    }, source)
    assert [segment["text"] for segment in selected] == ["x = 3"]
    assert selected[0]["content_role"] == "solution_working"


def test_prompt_overlap_backstop_rejects_misclassified_solution():
    canonical, _, _ = _build(
        "1.2 Determine the probability of success. (1)\nTOTAL: 1",
        _question("1.2", visual_text="x = 1"),
    )
    corrupted = deepcopy(canonical)
    item = _item(corrupted)
    block = item["alternatives"][0]["blocks"][0]
    block["type"] = "prose"
    block["text"] = "Determine the probability of success. (1) [1] QUESTION 2"
    block.pop("math", None)
    block["source_content_role"] = "solution_working"
    item["source_prompt"] = "Determine the probability of success."
    item["solution_evidence"]["prompt_text"] = item["source_prompt"]

    result = validate_canonical(corrupted)
    assert "question_prompt_used_as_solution" in result["error_codes"]
    assert "leaf_solution_missing" in result["error_codes"]
