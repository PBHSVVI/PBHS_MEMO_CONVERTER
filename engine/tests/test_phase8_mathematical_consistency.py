from __future__ import annotations

import time

import pytest

from engine.src.memo_engine.canonical import build_canonical_memo, validate_canonical
from engine.src.memo_engine.mathematical_consistency import (
    CHECKED_FAIL,
    CHECKED_PASS,
    MAX_FACTORIAL_OPERAND,
    NOT_CHECKED,
    check_canonical_mathematics,
    check_expression,
)


@pytest.mark.parametrize(
    "expression",
    [
        "(10 + 31 + 26) / 250 = 97 / 250 = 0.388",
        "10 / 250 = 1 / 25 = 9%",
        r"6! \times 2! / (2! \times 2!) = 180",
        "19.8567 = 18.9",
    ],
)
def test_proven_numeric_contradictions_fail(expression: str):
    result, _ = check_expression(expression)
    assert result["status"] == CHECKED_FAIL
    assert any(not relation["passed"] for relation in result["relations"])


@pytest.mark.parametrize(
    "expression",
    [
        r"8 \times 7 \times 6 \times 5 \times 4 = 8! / 3! = 6720",
        r"10 / 250 = \frac{1}{25} = 0.04 = 4\%",
        "10 / 250 = 1 / 25 = 0,04 = 4%",
        "15 / 20 = 75%",
        "0.52 = 52%",
        "50% = 0.5",
        "0.30(0.80) = 0.24",
    ],
)
def test_exact_numeric_chains_pass(expression: str):
    result, _ = check_expression(expression)
    assert result["status"] == CHECKED_PASS


def test_rounding_and_explicit_approximation_are_precision_aware():
    rounded, _ = check_expression("19.8567... = 19.9")
    approximate, _ = check_expression(r"17.49 \approx 17")
    bad, _ = check_expression("19.8567 = 18.9")
    assert rounded["status"] == CHECKED_PASS
    assert rounded["relations"][0]["evaluation_mode"] == "rounding"
    assert approximate["status"] == CHECKED_PASS
    assert approximate["relations"][0]["evaluation_mode"] == "approximate"
    assert bad["status"] == CHECKED_FAIL


@pytest.mark.parametrize(
    ("expression", "reason"),
    [
        (r"P(A \cup B) = P(A) + P(B) - P(A \cap B)", "unsupported_latex"),
        ("(35.9 - 19.9 ; 35.9 + 19.9) = (16 ; 55.8)", "pair_or_interval"),
        ("10, 31, 26", "ambiguous_comma"),
        ("__import__('os').system('x')", "unsupported_token"),
    ],
)
def test_unsupported_or_ambiguous_content_is_not_checked(expression: str, reason: str):
    result, _ = check_expression(expression)
    assert result["status"] == NOT_CHECKED
    assert result["reason"] == reason


def _math_block(block_id: str, expression: str) -> dict:
    return {
        "block_id": block_id,
        "type": "math",
        "semantic_role": "working",
        "math": {
            "source_text": expression,
            "canonical_latex": expression,
            "plain_text": expression,
            "display_mode": "display",
        },
        "source_refs": [{"file_id": "source_1", "page": 1}],
        "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
        "warnings": [],
    }


def _memo(alternatives: list[list[dict]]) -> dict:
    built_alternatives = []
    for index, blocks in enumerate(alternatives):
        built_alternatives.append({
            "alternative_id": f"q1_1_alt_{index}",
            "label": "PRIMARY" if index == 0 else f"OR {index}",
            "blocks": blocks,
            "marking_points": [{
                "mark_id": f"m{index}",
                "type": "answer",
                "count": 1,
                "descriptor": "answer",
                "applies_to_block_ids": [blocks[0]["block_id"]] if blocks else [],
                "source_shorthand": "1A",
                "consistent_accuracy": {"enabled": False, "dependency_item_ids": []},
                "acceptable_variants": [],
                "source_refs": [],
                "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
                "warnings": [],
            }],
            "marks_computed": 1,
            "source_refs": [],
        })
    return {
        "schema_version": "1.0",
        "document_id": "math-consistency-fixture",
        "status": "render_ready",
        "source": {
            "files": [{
                "file_id": "source_1", "original_filename": "fixture.pdf",
                "mime_type": "application/pdf", "sha256": "fixture",
                "acquisition_kind": "upload", "page_count": 1,
            }],
            "assets": [],
        },
        "document_metadata": {},
        "render_profile": "PBHS_GDE_INTERNAL_V1",
        "notes": [],
        "questions": [{
            "question_id": "q1", "number": "1", "heading": "QUESTION 1",
            "context_blocks": [],
            "items": [{
                "item_id": "q1_1", "number": "1.1", "context_blocks": [],
                "children": [], "alternatives": built_alternatives,
                "marks": {"observed": 1, "computed": 1, "status": "match"},
                "solution_evidence": {"source_question_id": "1.1"},
                "source_refs": [],
                "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
                "warnings": [],
            }],
            "subtotal": {"observed": 1, "computed": 1, "status": "match"},
            "source_refs": [],
            "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
            "warnings": [],
        }],
        "totals": {"observed": 1, "computed": 1, "expected": 1, "status": "match"},
        "exceptions": [], "corrections": [], "audit": {},
    }


def test_multiblock_continuation_fails_and_carries_both_block_ids():
    memo = _memo([[
        _math_block("b1", "10 / 250 = 1 / 25"),
        _math_block("b2", "= 9%"),
    ]])
    report = check_canonical_mathematics(memo)
    assert report["counts"] == {CHECKED_PASS: 1, CHECKED_FAIL: 1, NOT_CHECKED: 0}
    assert report["conflict_count"] == 1
    assert report["issues"][0]["suggestions"][0]["block_ids"] == ["b1", "b2"]


def test_context_resets_between_alternatives_and_questions():
    memo = _memo([
        [_math_block("b1", "1 / 25"), _math_block("b1b", "= 4%")],
        [_math_block("b2", "= 9")],
    ])
    report = check_canonical_mathematics(memo)
    assert report["counts"][CHECKED_PASS] == 2
    assert report["counts"][NOT_CHECKED] == 1
    assert report["conflict_count"] == 0

    second = _memo([[_math_block("b3", "= 9")]])["questions"][0]
    second["question_id"] = "q2"
    second["number"] = "2"
    second["items"][0]["item_id"] = "q2_1"
    second["items"][0]["number"] = "2.1"
    memo["questions"].append(second)
    report = check_canonical_mathematics(memo)
    assert report["counts"][NOT_CHECKED] == 2
    assert report["conflict_count"] == 0


def test_prose_and_figures_reset_continuation_and_are_not_evaluated():
    figure = {
        "block_id": "figure", "type": "figure", "semantic_role": "visual_answer",
        "figure": {"asset_id": "visual"}, "source_refs": [],
    }
    memo = _memo([[
        _math_block("b1", "1 / 25"),
        figure,
        _math_block("b2", "= 9%"),
    ]])
    report = check_canonical_mathematics(memo)
    assert report["counts"] == {CHECKED_PASS: 1, CHECKED_FAIL: 0, NOT_CHECKED: 1}
    assert report["issues"] == []


def test_validation_gate_blocks_proven_conflict_with_teacher_message():
    memo = _memo([[_math_block("b1", "6! * 2! / (2! * 2!) = 180")]])
    validation = validate_canonical(memo)
    assert validation["passed"] is False
    assert validation["gates"]["MATH_CONSISTENCY"] is False
    assert "mathematical_consistency_conflict" in validation["error_codes"]
    issue = next(
        item for item in validation["issues"]
        if item["category"] == "mathematical_consistency_conflict"
    )
    assert issue["message"] == "Displayed mathematical working is internally inconsistent."
    assert issue["suggestions"][0]["calculated_left"] == "360"
    assert issue["suggestions"][0]["displayed_right"] == "180"


def test_build_canonical_marks_conflicting_visual_solution_blocked():
    question = {
        "question_id": "1.1", "source_question_id": "1.1", "path": [1, 1],
        "depth": 2, "context_only": False, "source_block_index": 0,
        "source_page": 1, "source_character_offset": 0, "printed_marks": 1,
        "computed_shorthand_marks": 1, "mark_calculation_mode": "additive",
        "mark_points": [{"count": 1, "code": "A", "descriptor": "answer", "notation": "shorthand"}],
        "source_preview": "Calculate the value.",
        "visual_solution_segments": [{
            "text": "10 / 250 = 1 / 25 = 9%",
            "raw_transcription": "10 / 250 = 1 / 25 = 9%",
            "canonical_latex": "10 / 250 = 1 / 25 = 9%",
            "confidence": 0.98,
            "rendered_asset_ref": "internal/visual/synthetic.png",
            "source_ref": {"file_id": "source_1", "page": 1},
        }],
        "visual_evidence": [{"kind": "answer_working", "confidence": 0.98}],
    }
    normalized = {
        "job_id": "math-build-fixture",
        "source": {"sha256": "synthetic", "detected_kind": "pdf"},
        "content": {"kind": "pdf", "pages": [{"page": 1, "effective_text": "1.1 Calculate the value. (1)\nTOTAL: 1"}]},
    }
    semantic = {"phase": "phase4_semantics", "deterministic_results": [], "ai_results": [], "exceptions": [], "interpreter_runs": []}
    canonical, validation, _ = build_canonical_memo(
        {"id": "math-build-fixture", "source_filename": "fixture.pdf", "source_mime": "application/pdf"},
        {"source": {"sha256": "synthetic", "detected_kind": "pdf", "detected_mime": "application/pdf", "size_bytes": 1}},
        normalized,
        {"job_id": "math-build-fixture", "questions": [question], "subtotals": [], "exceptions": []},
        semantic,
        b"%PDF-synthetic",
    )
    assert validation["gates"]["MATH_CONSISTENCY"] is False
    assert canonical["status"] == "blocked"
    assert canonical["audit"]["mathematical_consistency"]["conflict_count"] == 1


def test_factorial_and_resource_limits_fail_closed():
    too_large, _ = check_expression(f"{MAX_FACTORIAL_OPERAND + 1}!")
    too_long, _ = check_expression("1+" * 300 + "1")
    assert too_large["status"] == NOT_CHECKED
    assert too_large["reason"] == "factorial_operand"
    assert too_long["status"] == NOT_CHECKED
    assert too_long["reason"] == "input_length_limit"


def test_checker_is_local_and_cheap_for_representative_fixture():
    memo = _memo([[
        _math_block(f"b{index}", f"{index} + 1 = {index + 1}")
        for index in range(1, 201)
    ]])
    started = time.perf_counter()
    report = check_canonical_mathematics(memo)
    elapsed = time.perf_counter() - started
    assert report["checked_expression_count"] == 200
    assert report["conflict_count"] == 0
    assert elapsed < 1.0

