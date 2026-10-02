from __future__ import annotations

from engine.src.memo_engine.corrections import apply_confirmed_corrections
from engine.src.memo_engine.semantic import interpret_semantics
from engine.src.memo_engine.ai_router import ProviderRun


def test_confirmed_unlabeled_question_is_promoted_without_mutating_source():
    normalized = {
        "job_id": "job",
        "content": {
            "units": [{
                "type": "table",
                "rows": [[
                    {"text": ""},
                    {"text": "Determine x"},
                    {"text": "✓ equations\n✓ elimination\n✓ common difference\n✓ first term (CA)"},
                    {"text": "(4)"},
                ]],
            }]
        },
    }
    structure = {
        "job_id": "job",
        "questions": [],
        "unlabeled_mark_blocks": [{
            "block_index": 0,
            "printed_allocations": [4],
            "candidate": "2.2",
        }],
        "exceptions": [{
            "level": "amber",
            "category": "unlabeled_mark_bearing_question",
            "affected_id": "2.2",
            "message": "unlabelled",
            "suggestions": [{"kind": "review_numbering", "candidate": "2.2"}],
        }],
        "summary": {},
    }
    corrections = [{
        "id": "corr-1",
        "confirmation_status": "confirmed",
        "proposed_patch": {
            "operation": "accept_suggestion",
            "category": "unlabeled_mark_bearing_question",
            "affected_id": "2.2",
            "suggestion": {"kind": "review_numbering", "candidate": "2.2"},
        },
    }]

    corrected, applied, issues = apply_confirmed_corrections(
        structure, normalized, corrections
    )

    assert issues == []
    assert len(applied) == 1
    assert corrected["questions"][0]["question_id"] == "2.2"
    assert corrected["questions"][0]["printed_marks"] == 4
    assert corrected["questions"][0]["computed_shorthand_marks"] == 4
    assert corrected["exceptions"] == []
    assert structure["questions"] == []  # original evidence object remains untouched


def test_partial_semantic_cache_reuses_identical_green_candidate(monkeypatch):
    structure = {
        "job_id": "job",
        "questions": [{
            "question_id": "2.2",
            "mark_points": [{
                "count": 1,
                "code": "A",
                "descriptor": "",
                "notation": "shorthand",
                "semantic": "other",
            }],
            "source_preview": "Determine x",
        }],
    }
    reusable = [{
        "candidate_id": "2_2__m1",
        "question_id": "2.2",
        "mark_index": 0,
        "count": 1,
        "source_shorthand": "A",
        "descriptor": "",
        "semantic_type": "accuracy",
        "confidence_score": 0.97,
        "band": "green",
        "rationale": "Prior safe classification.",
        "resolution_method": "groq:model",
        "provider_valid": True,
        "provider_validation_issue": None,
    }]

    result = interpret_semantics(structure, reusable_ai_results=reusable)

    assert result["summary"]["ai_candidate_count"] == 1
    assert result["summary"]["ai_cache_reused_count"] == 1
    assert result["summary"]["interpreter_run_count"] == 0
    assert result["ai_results"][0]["semantic_type"] == "accuracy"
    assert result["ai_results"][0]["resolution_method"].startswith("cache:")


def _semantic_conflict_structure():
    return {
        "job_id": "job",
        "questions": [{
            "question_id": "4.2.2",
            "source_block_index": 4,
            "printed_marks": 4,
            "computed_shorthand_marks": 4,
            "mark_points": [
                {"count": 1, "code": "M", "descriptor": "substitution", "notation": "shorthand", "semantic": "method"},
                {"count": 1, "code": "M", "descriptor": "working", "notation": "shorthand", "semantic": "method"},
                {"count": 1, "code": "R", "descriptor": "intermediate value", "notation": "shorthand", "semantic": "reason"},
                {"count": 1, "code": "A", "descriptor": "Correct c-value", "notation": "teacher_confirmed", "semantic": "accuracy"},
            ],
            "source_preview": "Question 4.2.2",
        }],
        "exceptions": [],
        "summary": {},
    }


def test_a_vs_ca_semantic_conflict_remains_teacher_review(monkeypatch):
    structure = _semantic_conflict_structure()

    def fake_classify(candidates, *, strong=False):
        results = []
        for candidate in candidates:
            semantic = "consistent_accuracy" if candidate["candidate_id"] == "4_2_2__m4" else "accuracy"
            results.append({
                "candidate_id": candidate["candidate_id"],
                "semantic_type": semantic,
                "confidence_score": 0.97,
                "band": "green",
                "rationale": "Descriptor-level semantic check.",
            })
        return ProviderRun("test", "semantic", len(candidates), None, None, None, 1, results)

    monkeypatch.setattr("engine.src.memo_engine.semantic.classify", fake_classify)
    result = interpret_semantics(structure)

    conflict = next(item for item in result["exceptions"] if item["affected_id"] == "4.2.2")
    assert conflict["category"] == "ambiguous_mark_semantics"
    assert conflict["suggestions"][0] == {
        "candidate_id": "4_2_2__m4",
        "question_id": "4.2.2",
        "mark_index": 3,
        "count": 1,
        "source_shorthand": "A",
        "descriptor": "Correct c-value",
        "semantic_type": "consistent_accuracy",
        "confidence_score": 0.97,
        "conflict_reason": "shorthand_semantic_conflict",
        "resolution_method": "test:semantic",
    }


def test_confirmed_semantic_choice_changes_only_selected_mark_and_prevents_repeat_review():
    structure = _semantic_conflict_structure()
    correction = {
        "id": "corr-semantic",
        "confirmation_status": "confirmed",
        "proposed_patch": {
            "operation": "resolve_mark_semantic_conflict",
            "category": "ambiguous_mark_semantics",
            "affected_id": "4.2.2",
            "candidate_id": "4_2_2__m4",
            "mark_index": 3,
            "source_count": 1,
            "source_code": "A",
            "source_descriptor": "Correct c-value",
            "selected_code": "CA",
            "selected_semantic_type": "consistent_accuracy",
        },
    }

    corrected, applied, issues = apply_confirmed_corrections(
        structure, {"job_id": "job", "content": {"units": []}}, [correction]
    )

    assert issues == []
    assert applied[0]["candidate_id"] == "4_2_2__m4"
    assert [point["code"] for point in corrected["questions"][0]["mark_points"]] == ["M", "M", "R", "CA"]
    assert corrected["questions"][0]["mark_points"][3]["notation"] == "teacher_semantic_confirmed"
    assert corrected["exceptions"] == []
    rerun = interpret_semantics(corrected)
    assert not any(item["affected_id"] == "4.2.2" for item in rerun["exceptions"])


def test_confirmed_keep_a_choice_is_explicit_and_not_silently_reinterpreted():
    structure = _semantic_conflict_structure()
    correction = {
        "id": "corr-keep-a", "confirmation_status": "confirmed",
        "proposed_patch": {
            "operation": "resolve_mark_semantic_conflict", "category": "ambiguous_mark_semantics",
            "affected_id": "4.2.2", "candidate_id": "4_2_2__m4", "mark_index": 3,
            "source_count": 1, "source_code": "A", "source_descriptor": "Correct c-value",
            "selected_code": "A", "selected_semantic_type": "accuracy",
        },
    }
    corrected, _, issues = apply_confirmed_corrections(
        structure, {"job_id": "job", "content": {"units": []}}, [correction]
    )
    assert issues == []
    assert corrected["questions"][0]["mark_points"][3]["code"] == "A"
    assert corrected["questions"][0]["mark_points"][3]["semantic"] == "accuracy"
    assert interpret_semantics(corrected)["exceptions"] == []
