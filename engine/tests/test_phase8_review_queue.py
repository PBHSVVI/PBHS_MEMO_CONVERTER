from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REVIEW_PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


def _section(name: str) -> str:
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    match = re.search(rf"// BEGIN {name}\s*(.*?)\s*// END {name}", html, flags=re.S)
    assert match, f"{name.lower()} is missing from the review page"
    return match.group(1)


def _evaluate(exceptions: list[dict]) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the review queue regression")
    program = (
        "const knownSpecs={};\n"
        + _section("REVIEW DEPENDENCY MODEL")
        + "\nconst list=JSON.parse(process.argv[1]);"
        + "\nlet state=reconcileReviewQueue(list,{});"
        + "\nconst first=state.selected_id;state=moveReviewQueue(state,1);const next=state.selected_id;"
        + "\nstate=moveReviewQueue(state,-1);const previous=state.selected_id;"
        + "\nstate=skipReviewQueue(state);"
        + "\nconsole.log(JSON.stringify({first,next,previous,skipped:state.selected_id,order:state.ids,actionable:actionableReviewQueue(list).map(x=>x.id)}));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(exceptions)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_previous_next_and_skip_rotate_only_actionable_items():
    exceptions = [
        {"id": "parent", "category": "question_total_mismatch", "affected_id": "7"},
        {"id": "first", "category": "ambiguous_mark_semantics", "affected_id": "7.2"},
        {"id": "second", "category": "item_total_mismatch", "affected_id": "8.1"},
        {"id": "third", "category": "numbering_jump", "affected_id": "9.1"},
    ]
    result = _evaluate(exceptions)

    assert result["actionable"] == ["first", "second", "third"]
    assert result["first"] == "first"
    assert result["next"] == "second"
    assert result["previous"] == "first"
    assert result["skipped"] == "second"
    assert result["order"] == ["second", "third", "first"]


def test_skipped_item_remains_unresolved_and_returns_after_other_items():
    result = _evaluate([
        {"id": "one", "category": "item_total_mismatch", "affected_id": "1.1"},
        {"id": "two", "category": "item_total_mismatch", "affected_id": "2.1"},
    ])
    assert set(result["order"]) == {"one", "two"}
    assert result["order"][-1] == "one"


def test_page_preserves_drafts_and_blocks_navigation_while_correction_is_pending():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "pbhs-review-draft:${jobId}:${exceptionId}" in html
    assert "saveDraft()" in html
    assert "restoreDraft(ex)" in html
    assert "Finish or cancel the saved correction before moving" in html
    assert "if(saved){" in html
    assert "if(saved&&saved.exception_id===body.exception_id)" not in html


def test_resume_reconciles_removed_confirmed_item_and_reports_advance():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "reconcileReviewQueue(list,saved)" in html
    assert "Saved ✓ — advanced to" in html
    assert "lastDecisionKey()" in html


def test_multiple_semantic_conflicts_have_question_progress_and_mark_position():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "semanticConflictProgress(ex,currentActive)" in html
    assert "Semantic conflict ${index+1} of ${peers.length} for Question ${ex.affected_id}" in html
    assert "semanticCandidateIndex" in html

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for semantic queue presentation regression")
    model = _section("SEMANTIC QUEUE PRESENTATION MODEL")
    exceptions = [
        {"id": "one", "category": "ambiguous_mark_semantics", "affected_id": "7.2", "suggestions": [{"candidate_id": "7_2__m2"}]},
        {"id": "two", "category": "ambiguous_mark_semantics", "affected_id": "7.2", "suggestions": [{"candidate_id": "7_2__m6"}]},
        {"id": "three", "category": "ambiguous_mark_semantics", "affected_id": "7.2", "suggestions": [{"candidate_id": "7_2__m8"}]},
    ]
    program = (
        "const actionableReviewQueue=list=>list;\n" + model
        + "\nconst list=JSON.parse(process.argv[1]);console.log(JSON.stringify(semanticConflictProgress(list[1],list)));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(exceptions)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert json.loads(result.stdout) == {
        "index": 2,
        "total": 3,
        "label": "Semantic conflict 2 of 3 for Question 7.2",
    }

def test_repeated_exception_generations_have_one_logical_queue_row():
    result = _evaluate([
        {"id": "old", "category": "item_total_mismatch", "affected_id": "5.1", "message": "Question 5.1 printed 3 but computed 2."},
        {"id": "new", "category": "item_total_mismatch", "affected_id": "5.1", "message": "Question 5.1 printed 3 but computed 2."},
    ])
    assert result["order"] == ["new"]
    assert result["first"] == "new"


def test_save_next_is_the_only_normal_confirmation_path():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "Save &amp; next" in html
    assert 'id="confirmApply"' not in html
    assert "Confirm, apply and recheck" not in html
    assert "invoke('confirm-correction',{correction_id:correction.id,defer_revalidation:true})" in html
    confirm_source = html.split("async function confirmCurrent()", 1)[1].split("async function applyStagedBatch", 1)[0]
    assert "resume-correction" not in confirm_source
    assert "monitorProcessing" not in confirm_source
    assert "Saved ✓" in confirm_source


def test_recheck_is_exposed_only_after_actionable_queue_is_empty():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert 'id="applyBatch" class="confirm hide">Recheck memo' in html
    assert "ready=staged.length>0&&remaining===0" in html
    assert "$('#applyBatch').classList.toggle('hide',!ready)" in html
    assert html.count("invoke('resume-correction'") == 1


def test_progress_uses_server_backed_staged_count_and_actionable_count():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert ".eq('confirmation_status','confirmed').is('applied_at',null)" in html
    assert "stagedDecisionCount=staged.length" in html
    assert "total=stagedDecisionCount+count" in html
    assert "Review ${position} of ${total}" in html


def test_bounded_item_editor_avoids_free_form_interpretation_route():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "['question_total_mismatch','item_total_mismatch','mark_arithmetic_mismatch']" in html
    assert "child_repair:{target_id:target,replacement_id:replacement,printed_marks:total,marking_text:markingText}" in html
