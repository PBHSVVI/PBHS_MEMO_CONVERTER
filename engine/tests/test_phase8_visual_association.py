from __future__ import annotations

import copy

from engine.src.memo_engine.corrections import apply_confirmed_corrections
from engine.src.memo_engine.visual_evidence import fuse_visual_evidence


ASSET = "internal/visual/regions/page-0005-q4_2.png"


def _observation(index: int, text: str = "4.2.23", *, asset: str = ASSET) -> dict:
    return {
        "evidence_id": f"evidence-{index:03d}",
        "question_ref": "4.2.1",
        "owned_question_ref": "4.2",
        "association_status": "cross_anchor_mismatch",
        "evidence_status": "cross_anchor_mismatch",
        "effective": False,
        "kind": "answer_working",
        "transcription": text,
        "normalized_math": text,
        "confidence": 0.97,
        "page": 5,
        "bbox": [10, 20, 30, 40],
        "source_page_bbox": [110, 220, 130, 240],
        "owned_bbox": [0, 180, 595, 260],
        "rendered_asset_ref": asset,
        "extractor_provider": "groq",
        "extractor_model": "synthetic-vision",
    }


def _structure() -> dict:
    return {
        "questions": [
            {"question_id": "4.2", "source_question_id": "4.2", "source_page": 3, "mark_points": []},
            {"question_id": "6.2", "source_question_id": "4.2", "source_page": 5, "mark_points": []},
            {"question_id": "6.3", "source_question_id": "6.3", "source_page": 5, "mark_points": []},
        ],
        "exceptions": [],
        "summary": {},
    }


def _visual(items: list[dict]) -> dict:
    return {"evidence": items, "mark_changes": [], "warnings": []}


def _patch(unit: dict, decision: str, target: str | None) -> dict:
    return {
        "schema_version": "1.0",
        "operation": "resolve_visual_evidence_association",
        "category": "visual_evidence_association_uncertain",
        "affected_id": "4.2",
        "decision": decision,
        "review_unit_id": unit["review_unit_id"],
        "evidence_ids": unit["evidence_ids"],
        "rendered_asset_ref": unit["rendered_asset_ref"],
        "source_page": unit["page"],
        "source_page_bboxes": unit["source_page_bboxes"],
        "owned_bbox": unit["owned_bbox"],
        "original_claimed_question_refs": unit["claimed_question_refs"],
        "original_owned_question_ref": unit["owned_question_ref"],
        "association_status": unit["association_status"],
        "target_id": target,
    }


def _correction(patch: dict) -> dict:
    return {
        "id": "visual-correction",
        "confirmation_status": "confirmed",
        "confirmed_at": "2026-10-18T10:00:00+00:00",
        "proposed_patch": patch,
    }


def test_forty_duplicate_observations_become_one_bounded_review_unit_without_losing_raw_evidence():
    visual = _visual([_observation(index) for index in range(40)])
    structure = fuse_visual_evidence(_structure(), visual)
    issues = [item for item in structure["exceptions"] if item["category"] == "visual_evidence_association_uncertain"]

    assert len(issues) == 1
    unit = issues[0]["suggestions"][0]
    assert unit["raw_observation_count"] == 40
    assert unit["transcriptions"] == ["4.2.23"]
    assert len(unit["evidence_ids"]) == 40
    assert unit["rendered_asset_ref"] == ASSET
    assert unit["page"] == 5
    assert unit["owned_question_ref"] == "4.2"
    assert len(visual["evidence"]) == 40


def test_distinct_readings_share_one_crop_unit_but_different_crops_never_merge():
    visual = _visual([
        _observation(1, "4.2.23"),
        _observation(2, "4.2.22"),
        _observation(3, "4.2.3"),
        _observation(4, "4.2.23", asset="internal/visual/regions/page-0003-q4_2.png"),
    ])
    structure = fuse_visual_evidence(_structure(), visual)
    units = [item["suggestions"][0] for item in structure["exceptions"] if item["category"] == "visual_evidence_association_uncertain"]

    assert len(units) == 2
    page_five = next(item for item in units if item["rendered_asset_ref"] == ASSET)
    assert page_five["transcriptions"] == ["4.2.23", "4.2.22", "4.2.3"]
    assert page_five["raw_observation_count"] == 3


def test_accept_uses_current_question_for_source_owner_and_attaches_only_that_target():
    visual = _visual([_observation(1, "x = 2"), _observation(2, "x = 2")])
    fused = fuse_visual_evidence(_structure(), visual)
    unit = fused["exceptions"][0]["suggestions"][0]

    result, applied, issues = apply_confirmed_corrections(
        fused, {}, [_correction(_patch(unit, "ACCEPT", "6.2"))], visual,
    )

    assert issues == []
    assert applied[0]["decision"] == "ACCEPT"
    q42 = next(item for item in result["questions"] if item["question_id"] == "4.2")
    q62 = next(item for item in result["questions"] if item["question_id"] == "6.2")
    q63 = next(item for item in result["questions"] if item["question_id"] == "6.3")
    assert len(q62["visual_evidence"]) == 2
    assert len(q62["visual_solution_segments"]) == 1
    assert "visual_evidence" not in q42
    assert "visual_evidence" not in q63
    assert not any(item["category"] == "visual_evidence_association_uncertain" for item in result["exceptions"])


def test_reassign_requires_explicit_existing_target_and_reject_preserves_raw_only():
    visual = _visual([_observation(1)])
    fused = fuse_visual_evidence(_structure(), visual)
    unit = fused["exceptions"][0]["suggestions"][0]

    reassigned, applied, issues = apply_confirmed_corrections(
        fused, {}, [_correction(_patch(unit, "REASSIGN", "6.3"))], visual,
    )
    assert issues == [] and applied[0]["target_id"] == "6.3"
    assert all("visual_evidence" not in item for item in reassigned["questions"] if item["question_id"] != "6.3")
    assert next(item for item in reassigned["questions"] if item["question_id"] == "6.3")["visual_evidence"][0]["association_resolution"]["decision"] == "REASSIGN"

    invalid, applied, issues = apply_confirmed_corrections(
        fused, {}, [_correction(_patch(unit, "REASSIGN", "9.9"))], visual,
    )
    assert applied == []
    assert issues[0]["category"] == "correction_target_invalid"

    rejected, applied, issues = apply_confirmed_corrections(
        fused, {}, [_correction(_patch(unit, "REJECT", None))], visual,
    )
    assert issues == [] and applied[0]["decision"] == "REJECT"
    assert all("visual_evidence" not in item for item in rejected["questions"])
    assert visual["evidence"][0]["effective"] is False
    assert visual["evidence"][0]["transcription"] == "4.2.23"


def test_missing_ambiguous_or_partial_evidence_identifiers_fail_closed():
    visual = _visual([_observation(1), _observation(2)])
    fused = fuse_visual_evidence(_structure(), visual)
    unit = fused["exceptions"][0]["suggestions"][0]

    partial = _patch(unit, "ACCEPT", "6.2")
    partial["evidence_ids"] = partial["evidence_ids"][:1]
    _, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(partial)], visual)
    assert applied == [] and issues[0]["category"] == "correction_evidence_unresolved"

    missing = _patch(unit, "ACCEPT", "6.2")
    missing["evidence_ids"] = ["missing"]
    _, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(missing)], visual)
    assert applied == [] and issues[0]["category"] == "correction_evidence_unresolved"

    ambiguous_visual = copy.deepcopy(visual)
    ambiguous_visual["evidence"].append(copy.deepcopy(ambiguous_visual["evidence"][0]))
    _, applied, issues = apply_confirmed_corrections(
        fused, {}, [_correction(_patch(unit, "ACCEPT", "6.2"))], ambiguous_visual,
    )
    assert applied == [] and issues[0]["category"] == "correction_evidence_unresolved"


def test_unrelated_operation_for_association_category_remains_unsupported():
    visual = _visual([_observation(1)])
    fused = fuse_visual_evidence(_structure(), visual)
    patch = {
        "operation": "set_question_subtotal",
        "category": "visual_evidence_association_uncertain",
        "affected_id": "4.2",
        "target_id": "6.2",
        "subtotal": 10,
    }
    _, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(patch)], visual)
    assert applied == []
    assert issues[0]["category"] == "correction_application_unsupported"
