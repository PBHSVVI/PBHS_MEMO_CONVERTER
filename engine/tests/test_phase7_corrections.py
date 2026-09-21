from __future__ import annotations

from engine.src.memo_engine.corrections import apply_confirmed_corrections
from engine.src.memo_engine.semantic import interpret_semantics


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
