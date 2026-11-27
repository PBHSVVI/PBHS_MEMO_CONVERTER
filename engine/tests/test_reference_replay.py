from __future__ import annotations

import copy

import pytest

from engine.src.memo_engine.reference_replay import CHECKS, apply_reference_results


def sample(diagram=False):
    review = {"category": "marking_interpretation_review", "affected_id": "3.1",
              "suggestions": [{"source_page": 2, "source_block_index": 7, "rendered_asset_ref": "crop.png"}]}
    points = []
    q = {"question_id": "3.1", "source_page": 2, "source_block_index": 7, "printed_marks": 2,
         "mark_points": points, "marking_interpretation": {"constructed": list(points), "unconfirmed": []}}
    structure = {"questions": [q], "exceptions": [review]}
    draft = {"working": [
        {"kind": "diagram_entry" if diagram else "math", "source_text": v, "latex": v, "alternative": 0}
        for v in ["7", "9"]
    ], "criteria": [{"marks": 1, "code": "A", "descriptor": label, "links": [index]}
                    for index, label in enumerate(["Left region", "Right region"])],
        "issue": "none", "marker_notes": []}
    result = {"printed_label": "3.1", "page": 2, "printed_allocation": 2, "artifact_digest": "a" * 64,
              "crop_sha256": "b" * 64, "draft": draft,
              "independent_verification": {"decision": "accept", "checks": {name: True for name in CHECKS}}}
    if diagram:
        point = {"count": 1, "code": "M", "descriptor": "Original left region award",
                 "criterion_id": "existing", "notation": "constructed_verified", "solution_evidence_ids": ["old"]}
        q["mark_points"].append(point)
        q["marking_interpretation"]["constructed"].append(point)
        q["visual_evidence"] = [{"evidence_id": "old", "normalized_math": "7"}]
        q["spatial_visual_groups"] = [{"reliable": True, "sha256": "image", "visual_evidence_ids": ["old"],
                                       "rendered_asset_ref": "crop.png"}]
    return structure, q, result


def test_reference_diagram_adds_only_missing_award_and_reuses_exact_figure():
    structure, question, result = sample(diagram=True)
    before = copy.deepcopy(question["mark_points"][0])
    image = question["spatial_visual_groups"][0]
    summary = apply_reference_results(structure, [result])
    assert summary["added_marking_points"] == 1
    assert question["computed_shorthand_marks"] == 2
    assert question["mark_points"][0] == before
    assert question["mark_points"][1]["descriptor"] == "Right region"
    assert image["sha256"] == "image" and image["rendered_asset_ref"] == "crop.png"
    assert question["mark_points"][1]["solution_evidence_ids"][0] in image["visual_evidence_ids"]
    assert not structure["exceptions"]


def test_source_wording_issue_keeps_review_and_improves_only_working():
    structure, question, result = sample()
    result["independent_verification"].update(decision="source_issue",
        finding="The maths matches. However, the sample and question name different groups; confirm the group.")
    summary = apply_reference_results(structure, [result])
    assert summary["source_issues_with_verified_working"] == 1
    assert not question["mark_points"]
    assert [line["canonical_latex"] for line in question["visual_solution_segments"]] == ["7", "9"]
    assert "sample and question name different groups" in structure["exceptions"][0]["message"]


def test_verified_working_cannot_score_under_a_conflicting_parent_heading():
    structure, question, result = sample()
    pending = {"category": "question_parent_heading_mismatch", "affected_id": "3.1",
               "suggestions": [{"source_page": 2, "source_block_index": 7}]}
    structure["exceptions"].append(pending)
    summary = apply_reference_results(structure, [result])
    assert summary["verified_working_pending_ownership"] == 1
    assert question["mark_points"] == []
    assert pending["suggestions"][0]["verified_working"] == ["7", "9"]
    assert structure["exceptions"][0]["suggestions"][0]["depends_on_source_numbering"]


def test_replay_rejects_unverified_provider_output():
    structure, _, result = sample()
    result["independent_verification"]["checks"]["fidelity"] = False
    with pytest.raises(ValueError, match="independent"):
        apply_reference_results(structure, [result])
