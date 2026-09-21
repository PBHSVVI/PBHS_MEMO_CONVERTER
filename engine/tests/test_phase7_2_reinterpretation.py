from __future__ import annotations

from engine.src.memo_engine.correction_reinterpretation import deterministic_proposal
from engine.src.memo_engine.corrections import apply_confirmed_corrections


def test_typed_numbering_correction_becomes_structured_rename():
    exception = {
        "category": "numbering_jump",
        "affected_id": "11.12.1",
    }
    proposal, display, evidence = deterministic_proposal(
        exception,
        "The correct question number is 11.2.1",
    )
    assert proposal == {
        "schema_version": "1.0",
        "operation": "rename_question_identifier",
        "category": "numbering_jump",
        "affected_id": "11.12.1",
        "target_id": "11.2.1",
        "reinterpretation_method": "deterministic_numbering_text",
    }
    assert display == "Rename Question 11.12.1 to Question 11.2.1."
    assert evidence["candidate_question_ids"] == ["11.2.1"]


def test_ambiguous_typed_numbering_stays_unresolved():
    exception = {
        "category": "numbering_jump",
        "affected_id": "11.12.1",
    }
    proposal, display, evidence = deterministic_proposal(
        exception,
        "Could be 11.2.1 or 11.3.1",
    )
    assert proposal is None
    assert display is None
    assert evidence["candidate_count"] == 2


def test_rename_overlay_preserves_original_source_identifier():
    structure = {
        "job_id": "job",
        "questions": [{
            "question_id": "11.12.1",
            "path": [11, 12, 1],
            "depth": 3,
            "context_only": False,
            "source_block_index": 0,
            "printed_marks": 4,
            "computed_shorthand_marks": 4,
            "mark_calculation_mode": "additive",
            "mark_points": [],
            "source_preview": "11.12.1 source working",
        }],
        "unlabeled_mark_blocks": [],
        "exceptions": [{
            "level": "amber",
            "category": "numbering_jump",
            "affected_id": "11.12.1",
            "message": "jump",
            "suggestions": [],
        }],
        "summary": {},
    }
    normalized = {"job_id": "job", "content": {"units": []}}
    corrections = [{
        "id": "corr",
        "confirmation_status": "confirmed",
        "proposed_patch": {
            "schema_version": "1.0",
            "operation": "rename_question_identifier",
            "category": "numbering_jump",
            "affected_id": "11.12.1",
            "target_id": "11.2.1",
        },
    }]
    corrected, applied, issues = apply_confirmed_corrections(
        structure, normalized, corrections
    )
    assert issues == []
    assert applied[0]["target_id"] == "11.2.1"
    question = corrected["questions"][0]
    assert question["question_id"] == "11.2.1"
    assert question["source_question_id"] == "11.12.1"
    assert corrected["exceptions"] == []
