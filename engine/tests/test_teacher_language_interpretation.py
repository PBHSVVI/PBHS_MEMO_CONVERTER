from __future__ import annotations

from copy import deepcopy

import pytest

from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine.correction_reinterpretation import (
    deterministic_proposal,
    interpret_evidence_ladder,
)
from engine.src.memo_engine.corrections import SUPPORTED_CORRECTION_OPERATIONS
from engine.src.memo_engine.phase7_5 import phase7_5_deterministic_proposal
from engine.src.memo_engine.teacher_language import (
    AI_RESPONSE_KEYS,
    TeacherLanguageError,
    ai_result_to_proposal,
    build_teacher_language_prompt,
    interpret_teacher_language,
    teacher_language_messages,
    teacher_language_response_schema,
    validate_teacher_language_response,
)


def _q(qid: str, *, block: int = 0, printed: int | None = None, computed: int = 0):
    return {
        "question_id": qid,
        "path": [int(part) for part in qid.split(".")],
        "depth": len(qid.split(".")),
        "context_only": False,
        "source_block_index": block,
        "printed_marks": printed,
        "computed_shorthand_marks": computed,
        "mark_calculation_mode": "additive",
        "mark_points": ([{
            "count": computed,
            "code": "A",
            "descriptor": "existing answer",
        }] if computed else []),
        "source_preview": qid,
    }


def _structure(question: dict, exception: dict, *, subtotals=None):
    return {
        "job_id": "job",
        "questions": [question],
        "unlabeled_mark_blocks": [],
        "subtotals": list(subtotals or []),
        "exceptions": [deepcopy(exception)],
        "summary": {},
    }


def _normalized(rows=None):
    rows = rows or [["source", "working", "1A existing answer", "(1)"]]
    return {
        "job_id": "job",
        "content": {
            "units": [{
                "type": "table",
                "rows": [[{"text": value} for value in row] for row in rows],
            }]
        },
    }


def _result(
    *,
    status="resolved",
    operation=None,
    affected_id=None,
    target_id=None,
    printed_marks=None,
    subtotal=None,
    expected_total=None,
    mark_calculation_mode=None,
    mark_points=None,
    reason="The teacher evidence is explicit.",
    evidence_basis=None,
    ambiguities=None,
):
    return {
        "status": status,
        "operation": operation,
        "affected_id": affected_id,
        "target_id": target_id,
        "printed_marks": printed_marks,
        "subtotal": subtotal,
        "expected_total": expected_total,
        "mark_calculation_mode": mark_calculation_mode,
        "mark_points": list(mark_points or []),
        "reason": reason,
        "evidence_basis": list(evidence_basis or []),
        "ambiguities": list(ambiguities or []),
    }


class FakeProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[bool] = []

    def __call__(self, context, *, strong=False):
        self.calls.append(strong)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response, {
            "provider": "groq",
            "model": "strong" if strong else "fast",
            "elapsed_ms": 12,
            "prompt_tokens": 20,
            "output_tokens": 10,
            "total_tokens": 30,
        }


def _context(text: str):
    return {
        "teacher_text": text,
        "source_excerpt": "bounded source excerpt",
        "current_question": None,
        "parent_discrepancies": [],
        "suggestions": [],
    }


def _always_valid(proposal):
    return True, None


def test_response_schema_is_closed_and_operation_allowlisted():
    schema = teacher_language_response_schema()
    assert SUPPORTED_CORRECTION_OPERATIONS == {
        "replace_mark_points",
        "set_item_total_override",
        "set_printed_marks",
        "rename_question_identifier",
        "promote_unlabeled_question",
        "insert_missing_major_question",
        "set_question_subtotal",
    }
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == AI_RESPONSE_KEYS
    assert "delete_question" not in schema["properties"]["operation"]["enum"]
    assert schema["properties"]["mark_points"]["items"]["additionalProperties"] is False


def test_prompt_is_bounded_and_contains_non_invention_rules():
    context = {
        "active_exception": {"category": "item_total_mismatch", "affected_id": "7.4"},
        "teacher_text": "one method mark",
        "source_excerpt": "x" * 5000,
        "allowed_operations": ["replace_mark_points"],
    }
    prompt = build_teacher_language_prompt(context)
    messages = teacher_language_messages(context)
    assert messages[0]["role"] == "system"
    assert "Never solve missing mathematics" in messages[0]["content"]
    assert "Never invent a question number" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": prompt}
    assert "replace_mark_points" in prompt
    assert len(prompt) < 7000


def test_existing_deterministic_numbering_stops_without_ai():
    exception = {"category": "numbering_jump", "affected_id": "11.12.1", "suggestions": []}
    structure = _structure(_q("11.12.1", printed=4, computed=4), exception)
    provider = FakeProvider(AssertionError("AI must not be called"))
    proposal, _, audit = interpret_evidence_ladder(
        exception,
        "This should be Question 11.2.1",
        structure,
        _normalized(),
        _context("This should be Question 11.2.1"),
        provider=provider,
    )
    assert proposal["operation"] == "rename_question_identifier"
    assert proposal["target_id"] == "11.2.1"
    assert audit["deterministic_resolution_count"] == 1
    assert provider.calls == []


def test_conditional_scoring_remains_deterministic_and_non_additive():
    exception = {"category": "correction_mark_total_invalid", "affected_id": "11.1.1"}
    structure = _structure(_q("11.1.1", printed=2, computed=3), exception)
    provider = FakeProvider(AssertionError("AI must not be called"))
    proposal, _, audit = interpret_evidence_ladder(
        exception,
        "2A for 3 correct answers; 1A for 2 correct answers",
        structure,
        _normalized([["11.1.1", "working", "2A for 3 correct answers\n1A for 2 correct answers", "(2)"]]),
        _context("2A for 3 correct answers; 1A for 2 correct answers"),
        provider=provider,
    )
    assert proposal["expected_total"] == 2
    assert proposal["mark_calculation_mode"] == "conditional_accuracy"
    assert audit["deterministic_resolution_count"] == 1
    assert provider.calls == []


def test_ambiguous_numbering_does_not_invent_target():
    exception = {"category": "numbering_jump", "affected_id": "11.12.1", "suggestions": []}
    ambiguous = _result(status="ambiguous", reason="Two targets remain.", ambiguities=["11.2.1 or 11.3.1"])
    provider = FakeProvider(ambiguous, ambiguous)
    proposal, _, audit = interpret_teacher_language(
        exception,
        "Could be 11.2.1 or 11.3.1",
        _context("Could be 11.2.1 or 11.3.1"),
        provider=provider,
        proposal_validator=_always_valid,
    )
    assert proposal is None
    assert provider.calls == [False, True]
    assert audit["strong_model_escalation_count"] == 1


def test_natural_item_total_is_resolved_deterministically():
    proposal, _, evidence = deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "7.4"},
        "This question is worth 4 marks",
    )
    assert proposal["operation"] == "set_item_total_override"
    assert proposal["printed_marks"] == 4
    assert evidence["teacher_item_total"] == 4


def test_corrected_parenthesized_total_is_resolved_deterministically():
    proposal, _, evidence = deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "7.4"},
        "The (3) is wrong, it should be (2)",
    )
    assert proposal["operation"] == "set_item_total_override"
    assert proposal["printed_marks"] == 2
    assert evidence["teacher_item_total"] == 2


def test_incompatible_item_total_fails_real_deterministic_validation():
    exception = {"category": "item_total_mismatch", "affected_id": "7.4", "suggestions": []}
    structure = _structure(_q("7.4", printed=3, computed=3), exception)
    provider = FakeProvider(_result(status="unsupported", reason="A mark scheme is required."))
    proposal, _, audit = interpret_evidence_ladder(
        exception,
        "This question is worth 4 marks",
        structure,
        _normalized([["7.4", "working", "3A existing", "(3)"]]),
        _context("This question is worth 4 marks"),
        provider=provider,
    )
    assert proposal is None
    assert audit["tier0"]["deterministic_validation"]["passed"] is False


@pytest.mark.parametrize(
    ("teacher_text", "points", "expected"),
    [
        (
            "One method mark for factorising and one answer mark",
            [
                {"count": 1, "code": "M", "descriptor": "factorising"},
                {"count": 1, "code": "A", "descriptor": "answer"},
            ],
            2,
        ),
        (
            "1M derivative, 1F factorisation, 1A critical values, 1A intervals",
            [
                {"count": 1, "code": "M", "descriptor": "derivative"},
                {"count": 1, "code": "F", "descriptor": "factorisation"},
                {"count": 1, "code": "A", "descriptor": "critical values"},
                {"count": 1, "code": "A", "descriptor": "intervals"},
            ],
            4,
        ),
    ],
)
def test_natural_mark_schemes_become_bounded_points(teacher_text, points, expected):
    exception = {"category": "mark_arithmetic_mismatch", "affected_id": "7.4"}
    result = _result(
        operation="replace_mark_points",
        affected_id="7.4",
        expected_total=expected,
        mark_calculation_mode="additive",
        mark_points=points,
    )
    proposal, display = ai_result_to_proposal(
        result, exception, _context(teacher_text), method="groq_fast_teacher_language"
    )
    assert proposal["expected_total"] == expected
    assert [point["code"] for point in proposal["mark_points"]] == [p["code"] for p in points]
    assert f"{expected}-mark scheme" in display


def test_natural_subtotal_is_deterministic():
    proposal, _, _ = phase7_5_deterministic_proposal(
        {"category": "subtotal_sum_unexpected", "affected_id": None},
        "Question 3 total is 4",
    )
    assert proposal["operation"] == "set_question_subtotal"
    assert proposal["target_id"] == "3"
    assert proposal["subtotal"] == 4


def test_invalid_subtotal_ledger_fails_real_deterministic_validation():
    exception = {"category": "subtotal_sum_unexpected", "affected_id": None, "suggestions": []}
    structure = {
        "job_id": "job",
        "questions": [_q(str(i), block=i) for i in range(1, 12)],
        "subtotals": [{"value": 140, "block_index": 1}],
        "exceptions": [deepcopy(exception)],
        "unlabeled_mark_blocks": [],
        "summary": {},
    }
    provider = FakeProvider(_result(status="unsupported", reason="The ledger does not support this."))
    proposal, _, audit = interpret_evidence_ladder(
        exception,
        "Question 3 total is 4",
        structure,
        _normalized([[str(i), "", "", ""] for i in range(1, 12)]),
        _context("Question 3 total is 4"),
        provider=provider,
    )
    assert proposal is None
    assert audit["tier0"]["deterministic_validation"]["passed"] is False


def test_unlabelled_row_natural_language_remains_deterministic():
    proposal, _, _ = deterministic_proposal(
        {"category": "unlabeled_mark_bearing_question", "affected_id": "2.2"},
        "That row is actually 2.2",
    )
    assert proposal["operation"] == "promote_unlabeled_question"
    assert proposal["target_id"] == "2.2"


def test_missing_major_natural_language_uses_structural_evidence():
    proposal, _, evidence = phase7_5_deterministic_proposal(
        {"category": "major_question_gap", "affected_id": "11.1.1"},
        "There should be a Question 10 here worth 5 marks",
    )
    assert proposal["operation"] == "insert_missing_major_question"
    assert proposal["target_id"] == "10"
    assert evidence["candidate_major_question_ids"] == ["10"]


def test_unsupported_ai_operation_is_rejected():
    value = _result(operation="delete_question", affected_id="7.4")
    with pytest.raises(TeacherLanguageError, match="outside the correction allowlist"):
        validate_teacher_language_response(value)


def test_wrong_affected_question_is_rejected():
    value = _result(
        operation="set_item_total_override", affected_id="7.3", printed_marks=4
    )
    with pytest.raises(TeacherLanguageError, match="different question"):
        ai_result_to_proposal(
            value,
            {"category": "item_total_mismatch", "affected_id": "7.4"},
            _context("This question is worth 4 marks"),
            method="groq_fast_teacher_language",
        )


def test_invented_mark_total_is_rejected():
    value = _result(
        operation="set_item_total_override", affected_id="7.4", printed_marks=5
    )
    with pytest.raises(TeacherLanguageError, match="not explicit"):
        ai_result_to_proposal(
            value,
            {"category": "item_total_mismatch", "affected_id": "7.4"},
            _context("This question is worth 4 marks"),
            method="groq_fast_teacher_language",
        )


def test_invented_mark_point_count_is_rejected():
    value = _result(
        operation="replace_mark_points",
        affected_id="7.4",
        expected_total=3,
        mark_calculation_mode="additive",
        mark_points=[
            {"count": 2, "code": "M", "descriptor": "factorising"},
            {"count": 1, "code": "A", "descriptor": "answer"},
        ],
    )
    with pytest.raises(TeacherLanguageError, match="mark counts, codes, or descriptions"):
        ai_result_to_proposal(
            value,
            {"category": "mark_arithmetic_mismatch", "affected_id": "7.4"},
            _context("One method mark for factorising and one answer mark"),
            method="groq_fast_teacher_language",
        )


def test_unexpected_ai_field_is_schema_rejected():
    value = _result(status="ambiguous")
    value["patch"] = {"path": "/questions/0"}
    with pytest.raises(TeacherLanguageError, match="exact correction contract"):
        validate_teacher_language_response(value)


def test_schema_failure_retains_provider_usage_audit():
    invalid = _result(status="ambiguous")
    invalid["unexpected"] = True
    provider = FakeProvider(invalid)
    proposal, _, audit = interpret_teacher_language(
        {"category": "item_total_mismatch", "affected_id": "7.4"},
        "Please fix this",
        _context("Please fix this"),
        provider=provider,
        proposal_validator=_always_valid,
    )
    assert proposal is None
    assert audit["runs"] == [{
        "provider": "groq",
        "model": "fast",
        "elapsed_ms": 12,
        "prompt_tokens": 20,
        "output_tokens": 10,
        "total_tokens": 30,
        "tier": "fast",
    }]
    assert audit["failure_code"] == "AI_SCHEMA_INVALID"


def test_provider_failure_preserves_unresolved_state_without_strong_loop():
    provider = FakeProvider(ProviderError("AI_RATE_LIMITED", "Try later", retryable=True))
    proposal, _, audit = interpret_teacher_language(
        {"category": "item_total_mismatch", "affected_id": "7.4"},
        "Please fix this",
        _context("Please fix this"),
        provider=provider,
        proposal_validator=_always_valid,
    )
    assert proposal is None
    assert provider.calls == [False]
    assert audit["provider_error"] == {"code": "AI_RATE_LIMITED", "retryable": True}
    assert audit["unresolved_count"] == 1


def test_fast_ambiguity_escalates_once_to_strong_resolution():
    ambiguous = _result(status="ambiguous", ambiguities=["wording is unclear"])
    resolved = _result(
        operation="rename_question_identifier",
        affected_id="11.12.1",
        target_id="11.2.1",
    )
    provider = FakeProvider(ambiguous, resolved)
    proposal, _, audit = interpret_teacher_language(
        {"category": "numbering_jump", "affected_id": "11.12.1", "suggestions": []},
        "Rename 11.12.1 to 11.2.1",
        _context("Rename 11.12.1 to 11.2.1"),
        provider=provider,
        proposal_validator=_always_valid,
    )
    assert proposal["target_id"] == "11.2.1"
    assert proposal["reinterpretation_method"] == "groq_strong_teacher_language"
    assert provider.calls == [False, True]
    assert audit["escalation_reason"] == "AI_RESULT_UNRESOLVED"


def test_fast_proposal_failing_overlay_validation_escalates_once():
    exception = {
        "category": "mark_arithmetic_mismatch",
        "affected_id": "7.4",
        "suggestions": [],
    }
    wrong = _result(
        operation="replace_mark_points",
        affected_id="7.4",
        expected_total=3,
        mark_calculation_mode="additive",
        mark_points=[
            {"count": 1, "code": "M", "descriptor": "factorising"},
            {"count": 1, "code": "A", "descriptor": "answer"},
            {"count": 1, "code": "A", "descriptor": "answer"},
        ],
    )
    correct = _result(
        operation="replace_mark_points",
        affected_id="7.4",
        expected_total=2,
        mark_calculation_mode="additive",
        mark_points=[
            {"count": 1, "code": "M", "descriptor": "factorising"},
            {"count": 1, "code": "A", "descriptor": "answer"},
        ],
    )
    provider = FakeProvider(wrong, correct)
    structure = _structure(_q("7.4", printed=2, computed=3), exception)
    proposal, _, audit = interpret_evidence_ladder(
        exception,
        "One method mark for factorising and one answer mark",
        structure,
        _normalized([["7.4", "working", "old scheme", "(2)"]]),
        _context("One method mark for factorising and one answer mark"),
        provider=provider,
    )
    assert proposal["expected_total"] == 2
    assert proposal["reinterpretation_method"] == "groq_strong_teacher_language"
    assert provider.calls == [False, True]
    assert audit["escalation_reason"] == "AI_PROPOSAL_DETERMINISTIC_REJECTED"
    assert audit["deterministic_validation"]["passed"] is True


def test_strong_unresolved_returns_review_without_proposal():
    ambiguous = _result(status="ambiguous", ambiguities=["insufficient evidence"])
    provider = FakeProvider(ambiguous, ambiguous)
    proposal, display, audit = interpret_teacher_language(
        {"category": "numbering_jump", "affected_id": "11.12.1", "suggestions": []},
        "Maybe change it",
        _context("Maybe change it"),
        provider=provider,
        proposal_validator=_always_valid,
    )
    assert proposal is None
    assert display is None
    assert audit["strong_model_escalation_count"] == 1
    assert audit["unresolved_count"] == 1
