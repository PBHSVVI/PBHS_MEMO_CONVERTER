from engine.src.memo_engine.correction_reinterpretation import deterministic_proposal


def test_bad_local_ocr_candidate_cannot_override_existing_numbering_suggestion():
    exception = {
        "category": "numbering_jump",
        "affected_id": "11.12.1",
        "suggestions": [{"kind": "review_numbering", "candidate": "11.2.1"}],
    }
    proposal, _, evidence = deterministic_proposal(exception, "11.7.1")
    assert proposal is None
    assert evidence["deterministic_suggestion_targets"] == ["11.2.1"]


def test_expected_identifier_still_produces_rename_proposal():
    exception = {
        "category": "numbering_jump",
        "affected_id": "11.12.1",
        "suggestions": [{"kind": "review_numbering", "candidate": "11.2.1"}],
    }
    proposal, display, _ = deterministic_proposal(exception, "11.2.1")
    assert proposal["operation"] == "rename_question_identifier"
    assert proposal["target_id"] == "11.2.1"
    assert "11.2.1" in display
