from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


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
    run = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(value)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(run.stdout)


def test_historical_rows_aggregate_by_physical_crop_and_keep_distinct_readings():
    model = _section("VISUAL ASSOCIATION REVIEW MODEL")
    value = {
        "rows": [
            {"id": "row-1", "category": "visual_evidence_association_uncertain", "affected_id": "4.2", "suggestions": [{"rendered_asset_ref": "internal/visual/regions/page-0005-q4_2.png", "page": 5, "owned_question_ref": "4.2", "claimed_question_ref": "4.2.1", "transcription": "4.2.23"}]},
            {"id": "row-2", "category": "visual_evidence_association_uncertain", "affected_id": "4.2", "suggestions": [{"rendered_asset_ref": "internal/visual/regions/page-0005-q4_2.png", "page": 5, "owned_question_ref": "4.2", "claimed_question_ref": "4.2.1", "transcription": "4.2.22"}]},
            {"id": "row-3", "category": "visual_evidence_association_uncertain", "affected_id": "4.2", "suggestions": [{"rendered_asset_ref": "internal/visual/regions/page-0003-q4_2.png", "page": 3, "owned_question_ref": "4.2", "claimed_question_ref": "4.2.1", "transcription": "other crop"}]},
        ],
        "visual": {"evidence": [
            {"evidence_id": "e1", "rendered_asset_ref": "internal/visual/regions/page-0005-q4_2.png", "page": 5, "owned_question_ref": "4.2", "question_ref": "4.2.1", "association_status": "cross_anchor_mismatch", "transcription": "4.2.23"},
            {"evidence_id": "e2", "rendered_asset_ref": "internal/visual/regions/page-0005-q4_2.png", "page": 5, "owned_question_ref": "4.2", "question_ref": "4.2.1", "association_status": "cross_anchor_mismatch", "transcription": "4.2.22"},
            {"evidence_id": "e3", "rendered_asset_ref": "internal/visual/regions/page-0003-q4_2.png", "page": 3, "owned_question_ref": "4.2", "question_ref": "4.2.1", "association_status": "cross_anchor_mismatch", "transcription": "other crop"},
        ], "mark_changes": []},
    }
    program = model + "\nconst v=JSON.parse(process.argv[1]);const out=await aggregateVisualAssociationRows(v.rows,v.visual);console.log(JSON.stringify(out.map(x=>({members:x.member_exception_ids,unit:x.suggestions[0]}))));"
    result = _node(program, value)

    assert len(result) == 2
    page_five = next(item for item in result if item["unit"]["page"] == 5)
    assert page_five["members"] == ["row-1", "row-2"]
    assert page_five["unit"]["transcriptions"] == ["4.2.23", "4.2.22"]
    assert page_five["unit"]["evidence_ids"] == ["e1", "e2"]
    assert page_five["unit"]["raw_observation_count"] == 2


def test_source_label_maps_to_current_question_after_numbering_correction():
    focus = _section("VISUAL EVIDENCE FOCUS MODEL")
    prelude = "function distinctValues(v){return [...new Set(v.filter(Boolean))]} function normalizedQuestionId(v){return String(v||'')} function majorQuestionId(v){return String(v).split('.')[0]} function compareQuestionIds(a,b){return String(a).localeCompare(String(b),undefined,{numeric:true})}\n"
    value = {
        "ex": {"affected_id": "4.2", "suggestions": [{"review_unit_type": "visual_evidence_association", "owned_question_ref": "4.2", "page": 5, "transcriptions": ["x=2"], "claimed_question_refs": ["4.2.1"]}]},
        "structure": {"questions": [
            {"question_id": "4.2", "source_question_id": "4.2", "source_page": 3},
            {"question_id": "6.2", "source_question_id": "4.2", "source_page": 5},
        ]},
    }
    program = prelude + focus + "\nconst v=JSON.parse(process.argv[1]);console.log(JSON.stringify(visualAssociationModel(v.ex,v.structure)));"
    result = _node(program, value)
    assert result["source_label"] == "4.2"
    assert result["current_question"] == "6.2"
    assert result["current_major"] == "6"
    assert result["page"] == 5


def test_ui_requires_explicit_bounded_choice_and_never_silently_selects_a_reading():
    source = PAGE.read_text(encoding="utf-8")
    assert "These are alternative or duplicate readings of one physical source region" in source
    assert "no reading is selected automatically" in source
    assert "Accept for" in source
    assert "Reassign selected question" in source
    assert "Reject as noise / unusable evidence" in source
    assert "submitVisualAssociationDecision" in source
    assert "Accept this reading" not in source


def test_association_showback_is_readable_and_keeps_identifiers_technical():
    showback = _section("TEACHER SHOWBACK MODEL")
    correction = {"display_text": "Reassign the visual observations from page 5 to Question 6.2.", "proposed_patch": {
        "operation": "resolve_visual_evidence_association", "decision": "REASSIGN",
        "target_id": "6.2", "source_page": 5, "original_owned_question_ref": "4.2",
        "original_claimed_question_refs": ["4.2.1"], "evidence_ids": ["e1", "e2"],
        "review_unit_id": "unit-1", "rendered_asset_ref": "internal/visual/regions/page-0005-q4_2.png",
    }}
    result = _node(showback + "\nconsole.log(JSON.stringify(teacherShowBackModel(JSON.parse(process.argv[1]))));", correction)
    assert result["association_choice"]["decision"] == "REASSIGN"
    assert result["association_choice"]["target_id"] == "6.2"
    assert result["association_choice"]["raw_count"] == 2
    source = PAGE.read_text(encoding="utf-8")
    assert '<summary>Technical details</summary>' in source
