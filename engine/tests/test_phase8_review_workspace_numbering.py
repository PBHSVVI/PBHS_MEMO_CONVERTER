from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.src.memo_engine.corrections import apply_confirmed_corrections


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"
SUBMIT = ROOT / "supabase" / "functions" / "submit-correction" / "index.ts"
CONFIRM = ROOT / "supabase" / "functions" / "confirm-correction" / "index.ts"


def _section(name: str) -> str:
    match = re.search(
        rf"// BEGIN {name}\s*(.*?)\s*// END {name}",
        PAGE.read_text(encoding="utf-8"),
        re.S,
    )
    assert match, f"missing JavaScript model: {name}"
    return match.group(1)


def _node(source: str, value: object) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    run = subprocess.run(
        [node, "--input-type=module", "-e", source, json.dumps(value)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(run.stdout)


def test_child_save_does_not_cover_parent_until_explicit_parent_done():
    model = _section("REVIEW DEPENDENCY MODEL")
    value = {
        "exceptions": [
            {"id": "parent", "category": "question_total_mismatch", "affected_id": "1"},
            {"id": "child", "category": "item_total_mismatch", "affected_id": "1.1"},
        ],
        "staged": [{
            "id": "one",
            "proposed_patch": {
                "operation": "replace_item_content",
                "category": "question_total_mismatch",
                "affected_id": "1",
                "target_id": "1.1",
                "reconciliation_scope": "suspicious_child",
            },
        }],
    }
    program = model + """
const x=JSON.parse(process.argv[1]);
const before=actionableReviewQueue(x.exceptions,x.staged).map(item=>item.id);
const after=actionableReviewQueue(x.exceptions,x.staged,new Set(['question:1'])).map(item=>item.id);
console.log(JSON.stringify({before,after,targets:[...stagedTargetSet(x.staged)]}));
"""
    result = _node(program, value)
    assert result == {
        "before": ["parent"],
        "after": [],
        "targets": ["question:1.1"],
    }


def test_explicit_parent_reconciliation_covers_parent():
    model = _section("REVIEW DEPENDENCY MODEL")
    value = {
        "exceptions": [{"id": "parent", "category": "question_total_mismatch", "affected_id": "2"}],
        "staged": [{"id": "parent-fix", "proposed_patch": {
            "operation": "set_question_subtotal", "affected_id": "2", "target_id": "2"
        }}],
    }
    program = model + "\nconst x=JSON.parse(process.argv[1]);console.log(JSON.stringify(actionableReviewQueue(x.exceptions,x.staged).map(item=>item.id)));"
    assert _node(program, value) == []


def test_three_children_remain_three_distinct_audit_entries():
    model = _section("REVIEW DEPENDENCY MODEL")
    staged = [
        {"id": f"corr-{child}", "exception_id": "parent", "proposed_patch": {
            "operation": "replace_item_content", "affected_id": "2", "target_id": f"2.{child}",
            "reconciliation_scope": "suspicious_child",
        }}
        for child in (1, 2, 4)
    ]
    program = model + "\nconst x=JSON.parse(process.argv[1]);console.log(JSON.stringify({rows:x.length,targets:[...stagedTargetSet(x)]}));"
    result = _node(program, staged)
    assert result["rows"] == 3
    assert result["targets"] == ["question:2.1", "question:2.2", "question:2.4"]


def test_structured_cross_major_numbering_is_exact_and_collision_safe():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    numbering = _section("STRUCTURED NUMBERING MODEL")
    program = dependency + numbering + """
const x=JSON.parse(process.argv[1]);
console.log(JSON.stringify({
 ok:structuredNumberingModel('4.1','6.1',x.ids,[]),
 collision:structuredNumberingModel('4.1','6.1',[...x.ids,'6.1'],[]),
 staged:structuredNumberingModel('4.1','6.1',x.ids,[{proposed_patch:{target_id:'6.1'}}])
}));
"""
    result = _node(program, {"ids": ["4.1", "4.2", "6.2"]})
    assert result["ok"] == {
        "current_id": "4.1",
        "correct_id": "6.1",
        "source_block_index": 0,
        "occurrence_count": 1,
        "operation": "rename_question_identifier",
        "display": "Rename Question 4.1 → Question 6.1",
    }
    assert "already exists" in result["collision"]["error"]
    assert "already staged" in result["staged"]["error"]
    assert "6.4.1" not in json.dumps(result)


def test_numbering_uses_confirmation_ready_deterministic_edge_path():
    page = PAGE.read_text(encoding="utf-8")
    submit = SUBMIT.read_text(encoding="utf-8")
    assert "numbering_correction" in page
    assert "numbering_correction" in submit
    assert 'operation: "rename_question_identifier"' in submit
    assert 'reinterpretation_method: "deterministic_structured_numbering_editor"' in submit
    branch = submit.split('} else if (numbering && typeof numbering === "object")', 1)[1].split(
        '} else if (parentResolution', 1
    )[0]
    assert "dispatchReinterpretation" not in branch
    assert '"ambiguous_numbering_source"' in branch
    assert "selectedMatches.length === 1" in branch
    assert "replacementConflict" in branch
    assert "currentId.startsWith" in branch


def test_cross_major_numbering_operation_preserves_source_provenance():
    structure = {
        "questions": [{
            "question_id": "4.1", "path": [4, 1], "depth": 2,
            "source_block_index": 12, "printed_marks": 3,
            "computed_shorthand_marks": 3, "mark_points": [],
        }],
        "exceptions": [{"category": "suspicious_question_identifier", "affected_id": "4.1"}],
        "summary": {},
    }
    correction = {
        "id": "rename-cross-major", "confirmation_status": "confirmed",
        "confirmed_at": "2026-10-15T09:00:00Z",
        "proposed_patch": {
            "operation": "rename_question_identifier",
            "category": "suspicious_question_identifier",
            "affected_id": "4.1", "source_id": "4.1",
            "target_id": "6.1", "replacement_id": "6.1",
            "correction_scope": "numbering_only",
        },
    }
    result, applied, issues = apply_confirmed_corrections(structure, {}, [correction])
    assert issues == []
    assert applied[0]["affected_id"] == "4.1"
    assert applied[0]["target_id"] == "6.1"
    assert result["questions"][0]["question_id"] == "6.1"
    assert result["questions"][0]["source_question_id"] == "4.1"
    assert result["questions"][0]["printed_marks"] == 3


def test_numbering_showback_and_edit_are_plain_teacher_language():
    page = PAGE.read_text(encoding="utf-8")
    assert "Rename Question ${esc(model.target_id)} → Question ${esc(model.replacement_id)}" in page
    assert "No other question wording, answer or mark allocation will change." in page
    assert "numbering?'Confirm':'Save & next'" in page
    assert "numbering||amendment?'Edit':'Edit / resubmit'" in page
    assert "editCurrentProposal" in page
    assert "$('#numberingCurrent').value=model.target_id" in page
    assert "$('#numberingCorrect').value=model.replacement_id" in page


def test_content_and_numbering_validation_remain_separate():
    page = PAGE.read_text(encoding="utf-8")
    assert "if(!questionText&&!solutionLines.length)" in page
    assert "Enter corrected question wording, corrected memo working, or both." in page
    numbering = page.split("async function submitNumbering()", 1)[1].split(
        "function parseStructuredMarking", 1
    )[0]
    assert "question_text" not in numbering
    assert "solution_lines" not in numbering


def test_home_is_persistent_navigation_and_never_signs_out_or_mutates():
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="homeLink"' in page
    assert 'href="../teacher-app/"' in page
    header = page.split("<header>", 1)[1].split("</header>", 1)[0]
    assert "signOut" not in header
    assert "invoke(" not in header
    assert 'id="signout"' in page


def test_durable_save_feedback_and_parent_workspace_retention_contract():
    page = PAGE.read_text(encoding="utf-8")
    confirm = CONFIRM.read_text(encoding="utf-8")
    assert "Saved ✓ — not applied yet" in page
    assert "Not saved —" in page
    assert "The backend did not return a durable confirmed correction." in page
    assert "The confirmed correction was not found in the staged ledger." in page
    assert "workspaceParent" in page
    assert "await showException(parent)" in page
    assert "Done with Question ${esc(major)} / Recheck Question ${esc(major)}" in page
    assert "blockUnsavedWorkspaceNavigation()" in page
    assert "before moving away" in page
    assert "Edit saved correction" in page
    assert "row.staged?'Edit saved correction':'Edit'" in page
    assert 'patch.correction_scope === "numbering_only"' in confirm
    assert "sameNumberingSource" in confirm
    assert "correction: confirmedCorrection" in confirm


def test_processing_copy_is_honest_and_has_no_fake_percentage():
    page = PAGE.read_text(encoding="utf-8")
    assert "Reading handwritten / visual annotations… This may take several minutes." in page
    assert "Estimated remaining" not in page
    assert "% complete" not in page
