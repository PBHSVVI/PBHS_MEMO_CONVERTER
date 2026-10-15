from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.src.memo_engine.corrections import (
    apply_confirmed_corrections,
    effective_correction_history,
)


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


def _question(qid: str, block: int, marks: int) -> dict:
    return {
        "question_id": qid,
        "path": [int(part) for part in qid.split(".")],
        "depth": len(qid.split(".")),
        "source_block_index": block,
        "printed_marks": marks,
        "computed_shorthand_marks": marks,
        "mark_points": [{"count": marks, "code": "A", "descriptor": qid, "source": f"{marks}A {qid}"}],
    }


def test_effective_staged_overlay_uses_amendment_once_and_preserves_history():
    old = {
        "id": "old-12", "confirmation_status": "confirmed", "confirmed_at": "2026-10-15T08:00:00Z",
        "proposed_patch": {"operation": "replace_item_content", "category": "question_total_mismatch", "affected_id": "1", "target_id": "1.2", "expected_total": 4},
    }
    new = {
        "id": "new-12", "confirmation_status": "confirmed", "confirmed_at": "2026-10-15T09:00:00Z",
        "proposed_patch": {"operation": "replace_item_content", "category": "question_total_mismatch", "affected_id": "1", "target_id": "1.2", "expected_total": 3, "supersedes_correction_id": "old-12"},
    }
    effective, history = effective_correction_history([old, new])
    assert [row["id"] for row in effective] == ["new-12"]
    assert history[0]["effective"] is False
    assert history[0]["superseded_by"] == "new-12"
    assert history[1]["effective"] is True


def test_question_workspace_projected_total_uses_latest_effective_staged_values():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    child = _section("CHILD REPAIR MODEL")
    support = r"""
function majorQuestionId(value){const match=String(value||'').match(/^\d+/);return match?match[0]:''}
"""
    program = dependency + support + child + r"""
const x=JSON.parse(process.argv[1]);
const model=questionLedgerModel(x.structure,x.exceptions,x.staged,'1');
console.log(JSON.stringify({projected:model.projected_total,rows:model.rows.map(row=>({id:row.question_id,total:row.projected,scheme:row.marking_text,correction:row.staged_correction_id})),effective:effectiveStagedCorrections(x.staged).map(item=>item.id)}));
"""
    value = {
        "structure": {"questions": [_question("1.1", 1, 0), _question("1.2", 2, 0)]},
        "exceptions": [{"id": "parent", "category": "question_total_mismatch", "affected_id": "1", "message": "Question 1 observed subtotal 7 does not equal computed 0."}],
        "staged": [
            {"id": "one", "proposed_patch": {"operation": "replace_item_content", "affected_id": "1", "target_id": "1.1", "expected_total": 4, "mark_points": [{"count": 4, "code": "A", "descriptor": "one", "source": "4A one"}]}},
            {"id": "old", "proposed_patch": {"operation": "replace_item_content", "affected_id": "1", "target_id": "1.2", "expected_total": 4, "mark_points": [{"count": 4, "code": "A", "descriptor": "old", "source": "4A old"}]}},
            {"id": "new", "proposed_patch": {"operation": "replace_item_content", "affected_id": "1", "target_id": "1.2", "expected_total": 3, "mark_points": [{"count": 3, "code": "A", "descriptor": "new", "source": "3A new"}], "supersedes_correction_id": "old"}},
        ],
    }
    result = _node(program, value)
    assert result["effective"] == ["one", "new"]
    assert result["projected"] == 7
    assert result["rows"][1] == {"id": "1.2", "total": 3, "scheme": "3A new", "correction": "new"}


def test_duplicate_numbering_requires_and_applies_stable_occurrence_locator():
    structure = {
        "questions": [_question("4.1", 4, 2), _question("4.1", 9, 3)],
        "exceptions": [{"category": "duplicate_question_identifier", "affected_id": "4.1"}],
        "summary": {},
    }
    correction = {
        "id": "rename-second", "confirmation_status": "confirmed", "confirmed_at": "2026-10-15T10:00:00Z",
        "proposed_patch": {
            "operation": "rename_question_identifier", "category": "duplicate_question_identifier",
            "affected_id": "4.1", "source_id": "4.1", "target_id": "6.1",
            "replacement_id": "6.1", "source_block_index": 9,
        },
    }
    result, applied, issues = apply_confirmed_corrections(structure, {}, [correction])
    assert issues == []
    assert [(q["question_id"], q["source_block_index"]) for q in result["questions"]] == [("4.1", 4), ("6.1", 9)]
    assert applied[0]["source_block_index"] == 9

    no_locator = {**correction, "id": "ambiguous", "proposed_patch": {k: v for k, v in correction["proposed_patch"].items() if k != "source_block_index"}}
    _, _, ambiguous_issues = apply_confirmed_corrections(structure, {}, [no_locator])
    assert ambiguous_issues[0]["category"] == "correction_evidence_unresolved"


def test_frontend_exposes_unflagged_editor_staged_amendment_and_pending_choices():
    page = PAGE.read_text(encoding="utf-8")
    assert "Edit any parsed question" in page
    assert "Automatic checks decide what needs attention first" in page
    assert "Edit saved correction" in page
    assert "The currently effective staged values are loaded below" in page
    assert "Replace the currently staged correction for Question" in page
    assert "Previous staged total" in page
    assert "New staged total" in page
    assert "Continue pending correction" in page
    assert "Edit pending correction" in page
    assert "Pending — not saved" in page


def test_edge_contracts_validate_amendment_manual_context_and_duplicate_occurrence():
    submit = SUBMIT.read_text(encoding="utf-8")
    confirm = CONFIRM.read_text(encoding="utf-8")
    assert 'error: "ambiguous_numbering_source"' in submit
    assert "source_block_index: selectedSourceIndex" in submit
    assert 'supersession_reason: "teacher_amended_previous_change"' in submit
    assert 'priorPatch?.operation !== "replace_item_content"' in submit
    assert 'reconciliation_scope: teacherInitiated ? "teacher_initiated_item"' in submit
    assert 'correction_scope: teacherInitiated ? "teacher_initiated_item"' in submit
    assert 'patch.correction_scope === "teacher_initiated_item"' in confirm
    assert "other.source_block_index" in confirm


def test_numbering_model_requires_occurrence_only_for_real_ambiguity():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    numbering = _section("STRUCTURED NUMBERING MODEL")
    program = dependency + numbering + r"""
const rows=[{question_id:'4.1',source_block_index:4},{question_id:'4.1',source_block_index:9},{question_id:'8.2',source_block_index:12}];
console.log(JSON.stringify({ambiguous:structuredNumberingModel('4.1','6.1',rows,[]),selected:structuredNumberingModel('4.1','6.1',rows,[],9),unique:structuredNumberingModel('8.2','8.3',rows,[])}));
"""
    result = _node(program, {})
    assert result["ambiguous"]["code"] == "ambiguous_numbering_source"
    assert result["selected"]["source_block_index"] == 9
    assert result["selected"]["correct_id"] == "6.1"
    assert result["unique"]["source_block_index"] == 12
    assert result["unique"]["correct_id"] == "8.3"
