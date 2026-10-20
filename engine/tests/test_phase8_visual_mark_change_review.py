from __future__ import annotations

import json
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from engine.src.memo_engine.phase7_5 import apply_phase7_5_patch


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


def _section(name: str) -> str:
    source = PAGE.read_text(encoding="utf-8")
    match = re.search(rf"// BEGIN {name}\s*(.*?)\s*// END {name}", source, re.S)
    assert match
    return match.group(1)


def _node(program: str, value: object) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(value)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _raw_rows() -> list[dict]:
    asset = "internal/visual/regions/page-0003-q4_1_1.png"
    return [
        {"id": "b657e6b9-ef1f-4564-ae3d-a5d6c00f357e", "category": "visual_mark_change_review", "affected_id": "4.1.1", "level": "amber", "suggestions": [{"level": "subtotal", "visual_value": 1, "printed_value": None, "rendered_asset_ref": asset}]},
        {"id": "d9ff2caf-6353-4f80-8bfe-546475638c6a", "category": "visual_mark_change_review", "affected_id": "4.1.1", "level": "amber", "suggestions": [{"level": "subtotal", "visual_value": 1, "printed_value": None, "rendered_asset_ref": asset}]},
        {"id": "fd07543f-ff19-4747-8dc5-48f30ac6d69b", "category": "visual_mark_change_review", "affected_id": "4.1.1", "level": "amber", "suggestions": [{"level": "subtotal", "visual_value": 2, "printed_value": None, "rendered_asset_ref": asset}]},
    ]


def test_three_raw_rows_become_one_auditable_logical_unit():
    association = _section("VISUAL ASSOCIATION REVIEW MODEL")
    value = {"rows": _raw_rows(), "visual": {"mark_changes": []}}
    program = association + "\nconst v=JSON.parse(process.argv[1]);const r=await aggregateVisualMarkChangeRows(v.rows,v.visual);console.log(JSON.stringify(r));"
    result = _node(program, value)
    assert len(result) == 1
    unit = result[0]["suggestions"][0]
    assert unit["review_unit_type"] == "visual_mark_change"
    assert unit["affected_question"] == "4.1.1"
    assert unit["source_page"] == 3
    assert unit["raw_observation_count"] == 3
    assert unit["candidates"] == [
        {"value": 1, "observation_count": 2, "evidence_ids": [], "member_exception_ids": [
            "b657e6b9-ef1f-4564-ae3d-a5d6c00f357e",
            "d9ff2caf-6353-4f80-8bfe-546475638c6a",
        ]},
        {"value": 2, "observation_count": 1, "evidence_ids": [], "member_exception_ids": [
            "fd07543f-ff19-4747-8dc5-48f30ac6d69b",
        ]},
    ]
    assert unit["member_exception_ids"] == [row["id"] for row in value["rows"]]


def test_review_model_never_preselects_majority_and_keeps_bounded_actions():
    model = _section("VISUAL MARK CHANGE REVIEW MODEL")
    unit = {
        "review_unit_type": "visual_mark_change",
        "review_unit_id": "unit-1",
        "affected_question": "4.1.1",
        "rendered_asset_ref": "internal/visual/regions/page-0003-q4_1_1.png",
        "source_page": 3,
        "level": "subtotal",
        "raw_observation_count": 3,
        "member_exception_ids": ["a", "b", "c"],
        "evidence_ids": ["e1", "e2", "e3"],
        "candidates": [{"value": 1, "observation_count": 2}, {"value": 2, "observation_count": 1}],
    }
    value = {"ex": {"category": "visual_mark_change_review", "affected_id": "4.1.1", "suggestions": [unit]}, "structure": {"questions": [{"question_id": "4.1.1", "source_block_index": 4}]}}
    program = "const visualDistinctValues=v=>[...new Set(v.map(String))];const effectiveStagedCorrections=v=>v;const markingSchemeText=p=>(p||[]).map(x=>x.source||`${x.count}${x.code} ${x.descriptor}`).join('\\n');\n" + model + "\nconst v=JSON.parse(process.argv[1]);const m=visualMarkChangeReviewModel(v.ex,v.structure,[]);console.log(JSON.stringify({m,use:visualMarkChangeResolutionPayload(m,'USE',2),reject:visualMarkChangeResolutionPayload(m,'REJECT')}));"
    result = _node(program, value)
    assert result["m"]["selected_value"] is None
    assert [item["value"] for item in result["m"]["candidates"]] == [1, 2]
    assert result["use"]["decision"] == "USE"
    assert result["use"]["selected_value"] == 2
    assert result["reject"]["decision"] == "REJECT"
    assert result["reject"]["selected_value"] is None


def test_mark_change_unit_controls_parent_dependency_as_one_unit():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    unit = {"review_unit_type": "visual_mark_change", "review_unit_id": "unit-1"}
    child = {"id": "child", "category": "visual_mark_change_review", "affected_id": "4.1.1", "suggestions": [unit]}
    parent = {"id": "parent", "category": "question_total_mismatch", "affected_id": "4"}
    staged = {"id": "decision", "proposed_patch": {"operation": "resolve_visual_mark_change", "target_id": "4.1.1", "visual_mark_change_review_unit_id": "unit-1"}}
    value = {"child": child, "parent": parent, "staged": staged}
    program = "const v=JSON.parse(process.argv[1]);\n" + dependency + "\nconsole.log(JSON.stringify({before:isDependent(v.parent,[v.parent,v.child],[]),after:isDependent(v.parent,[v.parent,v.child],[v.staged]),covered:exceptionCoveredByTargets(v.child,stagedTargetSet([v.staged]))}));"
    assert _node(program, value) == {"before": True, "after": False, "covered": True}


def test_dedicated_ui_requires_complete_scheme_and_has_no_reassignment_or_ai_call():
    source = PAGE.read_text(encoding="utf-8")
    card = source.split("function renderVisualMarkChangeCard", 1)[1].split("async function renderChoices", 1)[0]
    submit = source.split("async function submitChildRepair", 1)[1].split("function safeName", 1)[0]
    assert "Use ${esc(item.value)} mark" in card
    assert "observation${item.observation_count===1?'':'s'}" in card
    assert "Ignore visual mark change / keep source state" in card
    assert "Review this mark correction" in card
    assert "Reassign" not in card
    assert "submitSuggestion" not in card
    assert "invoke(" not in card
    assert "submitVisualMarkChangeAgreement" in card
    assert "submitVisualMarkChangeEditor" in card
    assert "if(value===model.effective_total)submitVisualMarkChangeAgreement" in card
    assert "else open('USE',value)" in card
    assert "manualVisualMark').onclick=()=>open('MANUAL',model.effective_total)" in card
    assert "enter both the question total and the complete marking scheme" in submit
    assert "parsed.total!==total" in submit
    assert "visual_mark_change_resolution" in submit


def test_reject_replays_without_changing_source_marks():
    structure = {
        "questions": [{"question_id": "4.1.1", "printed_marks": None, "mark_points": []}],
        "exceptions": [
            {"category": "visual_mark_change_review", "affected_id": "4.1.1"},
            {"category": "question_total_mismatch", "affected_id": "4"},
        ],
    }
    before = deepcopy(structure["questions"])
    patch = {
        "operation": "resolve_visual_mark_change",
        "affected_id": "4.1.1",
        "target_id": "4.1.1",
        "decision": "REJECT",
        "visual_mark_change_decision": "REJECT",
        "visual_mark_change_review_unit_id": "unit-1",
        "visual_mark_change_member_exception_ids": ["a", "b", "c"],
    }
    applied, issue, handled = apply_phase7_5_patch(
        structure, {}, correction_id="corr", category="visual_mark_change_review",
        affected_id="4.1.1", operation="resolve_visual_mark_change", patch=patch,
    )
    assert handled and issue is None
    assert applied["source_state_preserved"] is True
    assert structure["questions"] == before
    assert structure["exceptions"] == [{"category": "question_total_mismatch", "affected_id": "4"}]


def test_visual_mark_content_change_reuses_strict_mark_validation_and_audit():
    structure = {
        "questions": [{"question_id": "4.1.1", "path": [4, 1, 1], "depth": 3, "source_block_index": 4, "printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []}],
        "exceptions": [{"category": "visual_mark_change_review", "affected_id": "4.1.1"}],
    }
    patch = {
        "operation": "replace_item_content", "affected_id": "4.1.1", "target_id": "4.1.1", "replacement_id": "4.1.1",
        "question_text": None, "solution_lines": [], "printed_marks": 2, "expected_total": 2,
        "mark_points": [{"count": 1, "code": "M", "descriptor": "method", "source": "1M method"}, {"count": 1, "code": "A", "descriptor": "answer", "source": "1A answer"}],
        "reconciliation_scope": "bounded_item_editor", "visual_mark_change_decision": "USE",
        "visual_mark_change_review_unit_id": "unit-1", "visual_mark_change_member_exception_ids": ["a", "b", "c"],
    }
    applied, issue, handled = apply_phase7_5_patch(
        structure, {}, correction_id="corr", category="visual_mark_change_review",
        affected_id="4.1.1", operation="replace_item_content", patch=patch,
    )
    assert handled and issue is None
    assert applied["mark_total"] == 2
    assert applied["visual_mark_change_review_unit_id"] == "unit-1"
    assert structure["questions"][0]["correction_overlay"]["visual_mark_change_decision"] == "USE"
    assert not structure["exceptions"]


def test_matching_visual_value_resolves_without_rewriting_effective_item_and_is_replay_safe():
    original_question = {
        "question_id": "4.1.2",
        "path": [4, 1, 2],
        "depth": 3,
        "source_block_index": 2,
        "printed_marks": 1,
        "computed_shorthand_marks": 1,
        "mark_points": [{"count": 1, "code": "A", "descriptor": "accepted answer"}],
        "correction_overlay": {"correction_id": "earlier-content-fix"},
    }
    patch = {
        "operation": "resolve_visual_mark_change",
        "affected_id": "4.1.2",
        "target_id": "4.1.2",
        "decision": "USE",
        "visual_mark_change_decision": "USE",
        "visual_mark_change_selected_value": 1,
        "visual_mark_change_matches_effective_total": True,
        "visual_mark_change_review_unit_id": "unit-q412",
        "visual_mark_change_member_exception_ids": ["member-1"],
        "visual_mark_change_evidence_ids": ["evidence-1"],
        "source_block_index": 2,
    }

    for correction_id in ("first-replay", "second-replay"):
        structure = {
            "questions": [deepcopy(original_question)],
            "exceptions": [{"category": "visual_mark_change_review", "affected_id": "4.1.2"}],
        }
        applied, issue, handled = apply_phase7_5_patch(
            structure, {}, correction_id=correction_id,
            category="visual_mark_change_review", affected_id="4.1.2",
            operation="resolve_visual_mark_change", patch=patch,
        )
        assert handled and issue is None
        assert structure["questions"] == [original_question]
        assert structure["exceptions"] == []
        assert applied["visual_mark_change_decision"] == "USE"
        assert applied["visual_mark_change_selected_value"] == 1
        assert applied["visual_mark_change_review_unit_id"] == "unit-q412"
        assert applied["visual_mark_change_member_exception_ids"] == ["member-1"]
        assert applied["visual_mark_change_evidence_ids"] == ["evidence-1"]
        assert applied["source_state_preserved"] is True


def test_matching_candidate_model_uses_effective_item_state_without_mark_points_payload():
    model = _section("VISUAL MARK CHANGE REVIEW MODEL")
    unit = {
        "review_unit_type": "visual_mark_change",
        "review_unit_id": "unit-q412",
        "affected_question": "4.1.2",
        "rendered_asset_ref": "internal/visual/regions/page-0003-q4_1_1.png",
        "source_page": 3,
        "level": "subtotal",
        "raw_observation_count": 1,
        "member_exception_ids": ["member-1"],
        "evidence_ids": ["evidence-1"],
        "candidates": [{"value": 1, "observation_count": 1}],
    }
    value = {
        "ex": {"category": "visual_mark_change_review", "affected_id": "4.1.2", "suggestions": [unit]},
        "structure": {"questions": [{
            "question_id": "4.1.2", "source_block_index": 2,
            "printed_marks": 1, "computed_shorthand_marks": 1,
            "mark_points": [{"count": 1, "code": "A", "descriptor": "accepted answer", "source": "1A accepted answer"}],
        }]},
    }
    program = "const visualDistinctValues=v=>[...new Set(v.map(String))];const effectiveStagedCorrections=v=>v;const markingSchemeText=p=>(p||[]).map(x=>x.source||`${x.count}${x.code} ${x.descriptor}`).join('\\n');\n" + model + "\nconst v=JSON.parse(process.argv[1]);const m=visualMarkChangeReviewModel(v.ex,v.structure,[]);const payload=visualMarkChangeResolutionPayload(m,'USE',1);console.log(JSON.stringify({m,payload}));"
    result = _node(program, value)
    assert result["m"]["effective_total"] == 1
    assert result["m"]["source_block_index"] == 2
    assert result["payload"]["decision"] == "USE"
    assert result["payload"]["selected_value"] == 1
    assert result["payload"]["effective_item_total"] == 1
    assert result["payload"]["source_block_index"] == 2
    assert "mark_points" not in result["payload"]


def test_same_textual_identifier_on_another_page_cannot_join_visual_unit():
    association = _section("VISUAL ASSOCIATION REVIEW MODEL")
    rows = _raw_rows()[:1] + [{
        "id": "page-5-member",
        "category": "visual_mark_change_review",
        "affected_id": "4.1.1",
        "level": "amber",
        "suggestions": [{
            "level": "subtotal", "visual_value": 1, "printed_value": None,
            "rendered_asset_ref": "internal/visual/regions/page-0005-q4_1_1.png",
        }],
    }]
    program = association + "\nconst v=JSON.parse(process.argv[1]);const r=await aggregateVisualMarkChangeRows(v.rows,{mark_changes:[]});console.log(JSON.stringify(r));"
    result = _node(program, {"rows": rows})
    assert len(result) == 2
    assert {item["suggestions"][0]["source_page"] for item in result} == {3, 5}
