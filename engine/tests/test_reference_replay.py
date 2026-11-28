from __future__ import annotations

import copy

import pytest

from engine.src.memo_engine.corrections import apply_confirmed_corrections
from engine.src.memo_engine.structure import source_line_hash
from engine.src.memo_engine.reference_replay import CHECKS, apply_reference_results, apply_renumbered_reference_results


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


@pytest.mark.parametrize("target,source_block,admitted", [("12.1", 7, True), ("11.1", 7, False), ("12.1", 1, False)])
def test_reference_marking_admitted_only_after_exact_confirmed_rename(target, source_block, admitted):
    structure, question, entry = sample()
    question.update(source_heading_major="12", source_character_offset=100, path=[3, 1])
    structure["exceptions"][0]["suggestions"][0]["source_occurrence"] = "3.1@2:100"
    other = {"question_id": "3.1", "source_page": 1, "source_block_index": 1, "path": [3, 1],
             "source_heading_major": "3", "source_character_offset": 200, "mark_points": [{"count": 1}]}
    structure["questions"].append(other)
    category = "question_parent_heading_mismatch"
    structure["exceptions"].append({"category": category, "affected_id": "3.1",
                                   "suggestions": [{"source_page": 2, "source_block_index": 7}]})
    structure["exceptions"].append({"category": "duplicate_question_identifier", "affected_id": "3.1"})
    pending = []
    apply_reference_results(structure, [entry], pending_numbering=pending)
    correction = {"id": "confirmed-rename", "confirmation_status": "confirmed", "proposed_patch": {
        "category": category, "affected_id": "3.1", "operation": "rename_question_identifier",
        "target_id": target, "source_block_index": source_block,
    }}
    corrected, applied, issues = apply_confirmed_corrections(structure, {}, [correction])
    assert issues == [] and len(applied) == 1
    review, = [row for row in corrected["exceptions"] if row["category"] == "marking_interpretation_review"]
    assert any(row["category"] == category for row in corrected["exceptions"]) is (source_block != 7)
    assert review["affected_id"] == (target if source_block == 7 else "3.1")
    assert review["suggestions"][0]["source_occurrence"] == "3.1@2:100"
    assert apply_renumbered_reference_results(corrected, pending, applied) == int(admitted)
    after = next(q for q in corrected["questions"] if q["source_page"] == 2)
    assert sum(point["count"] for point in after["mark_points"]) == (2 if admitted else 0)
    assert corrected["questions"][0]["mark_points"] == [{"count": 1}]
    assert any(row["category"] == "marking_interpretation_review" for row in corrected["exceptions"]) is not admitted
    if admitted:
        assert after["reference_verification"]["numbering_correction_id"] == "confirmed-rename"
        assert [line["canonical_latex"] for line in after["visual_solution_segments"]] == ["7", "9"]
        assert apply_renumbered_reference_results(corrected, pending, applied) == 0


def test_replay_rejects_unverified_provider_output():
    structure, _, result = sample()
    result["independent_verification"]["checks"]["fidelity"] = False
    with pytest.raises(ValueError, match="independent"):
        apply_reference_results(structure, [result])


def test_group_numbering_is_atomic_and_follow_up_keeps_verified_working():
    structure, question, entry = sample()
    question.update(path=[3, 1], source_heading_major="12", source_character_offset=100,
                    source_line="3.1 Calculate this.")
    structure["exceptions"][0]["suggestions"][0]["source_occurrence"] = "3.1@2:100"
    other = {"question_id": "3.2", "source_page": 2, "source_block_index": 7, "path": [3, 2],
             "source_heading_major": "12", "source_character_offset": 200, "source_line": "3.2 Explain.",
             "printed_marks": 1, "mark_points": [{"count": 1}]}
    original = {**other, "source_page": 1, "source_block_index": 1, "source_heading_major": "3"}
    structure["questions"].extend([original, other])
    category = "question_parent_heading_mismatch"
    for q in (question, other):
        structure["exceptions"].append({"category": category, "affected_id": q["question_id"],
                                       "suggestions": [{"source_page": 2, "source_block_index": 7}]})
    pending = []
    apply_reference_results(structure, [entry], pending_numbering=pending)
    members = [
        {"affected_id": q["question_id"], "target_id": "12." + q["question_id"].split(".")[1],
         "source_block_index": 7, "source_locator": {"schema_version": "1.0", "parent_heading": "12",
          "source_page": 2, "source_question_id": q["question_id"], "source_line_hash": source_line_hash(q["source_line"])}}
        for q in (question, other)
    ]
    numbering = {"id": "numbering", "confirmation_status": "confirmed", "proposed_patch": {
        "category": category, "affected_id": "3.1", "operation": "rename_question_family",
        "numbering_members": members,
    }}
    broken = copy.deepcopy(numbering)
    broken["proposed_patch"]["numbering_members"][1]["target_id"] = "12.1"
    unchanged, applied, issues = apply_confirmed_corrections(structure, {}, [broken])
    assert not applied and len(issues) == 1
    assert unchanged["questions"] == structure["questions"]

    marking = {"id": "marks", "confirmation_status": "confirmed", "proposed_patch": {
        "category": "teacher_initiated_item_edit", "operation": "replace_item_content", "affected_id": "12.1",
        "target_id": "12.1", "numbering_correction_id": "numbering", "source_block_index": 7,
        "source_locator": members[0]["source_locator"], "reconciliation_scope": "teacher_initiated_item",
        "solution_lines": [], "printed_marks": 2, "mark_points": [
            {"count": 1, "code": "M", "descriptor": "Teacher method"},
            {"count": 1, "code": "A", "descriptor": "Teacher answer"},
        ],
    }}
    final, applied, issues = apply_confirmed_corrections(structure, {}, [numbering, marking])
    assert not issues
    assert [item["correction_id"] for item in applied] == ["numbering", "marks"]
    assert [q["question_id"] for q in final["questions"]] == ["3.2", "12.1", "12.2"]
    assert final["questions"][0] == original
    assert apply_renumbered_reference_results(final, pending, applied) == 1
    after = final["questions"][1]
    assert [p["descriptor"] for p in after["mark_points"]] == ["Teacher method", "Teacher answer"]
    assert [line["canonical_latex"] for line in after["visual_solution_segments"]] == ["7", "9"]
    assert all(row["effective"] and row["applied"] for row in final["correction_overlay"]["history"])


@pytest.mark.parametrize("solution_lines", [[], ["6! / (2! × 2!) = 180"]])
def test_numbered_calculation_review_is_resolved_only_by_working_for_its_source(solution_lines):
    structure, question, _ = sample()
    question.update(path=[3, 1], source_heading_major="12", source_character_offset=100,
                    source_line="3.1 Calculate this.")
    earlier = {**question, "source_page": 1, "source_block_index": 2, "source_heading_major": "3"}
    structure["questions"].insert(0, earlier)
    hint = structure["exceptions"][0]["suggestions"][0]
    hint.update(source_occurrence="3.1@2:100", guideline_math_conflict_only=True)
    earlier_review = {"category": "marking_interpretation_review", "affected_id": "3.1",
                      "suggestions": [{**hint, "source_page": 1, "source_block_index": 2, "source_occurrence": "3.1@1:100"}]}
    structure["exceptions"].append(earlier_review)
    locator = {"schema_version": "1.0", "parent_heading": "12", "source_page": 2,
               "source_question_id": "3.1", "source_character_offset": 100,
               "source_line_hash": source_line_hash(question["source_line"])}
    rename = {"id": "number", "confirmation_status": "confirmed", "proposed_patch": {
        "operation": "rename_question_identifier", "category": "question_parent_heading_mismatch",
        "affected_id": "3.1", "target_id": "12.1", "source_block_index": 7, "source_locator": locator,
    }}
    amendment = {"id": "working", "confirmation_status": "confirmed", "proposed_patch": {
        "operation": "replace_item_content", "category": "teacher_initiated_item_edit",
        "source_exception_category": "mathematical_consistency_conflict", "affected_id": "12.1", "target_id": "12.1",
        "numbering_correction_id": "number", "source_block_index": 7, "source_locator": locator,
        "reconciliation_scope": "teacher_initiated_item", "reinterpretation_method": "structured_numbered_marking",
        "solution_lines": solution_lines, "printed_marks": 2, "mark_points": [
            {"count": 1, "code": "M", "descriptor": "Method"},
            {"count": 1, "code": "A", "descriptor": "Answer"},
        ],
    }}
    final, applied, issues = apply_confirmed_corrections(structure, {}, [rename, amendment])
    assert not issues and len(applied) == 2
    assert final["questions"][0] == earlier
    assert earlier_review in final["exceptions"]
    assert any(row["affected_id"] == "12.1" for row in final["exceptions"]) is not bool(solution_lines)
    if solution_lines:
        assert final["questions"][1]["content_override"]["solution_lines"] == solution_lines
