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


def test_source_restoration_supersedes_bad_parent_mark_and_preserves_children():
    structure = {
        "questions": [
            _question("2.1", 1, 0),
            _question("2.1.1", 2, 1),
            _question("2.1.2", 3, 1),
            _question("2.2", 4, 2),
            _question("2.3", 5, 2),
            _question("2.4", 6, 3),
        ],
        "exceptions": [],
        "summary": {},
    }
    structure["questions"][0]["printed_marks"] = None
    structure["questions"][0]["computed_shorthand_marks"] = 0
    structure["questions"][0]["mark_points"] = []
    old = {
        "id": "old-21", "confirmation_status": "confirmed", "confirmed_at": "2026-10-19T08:00:00Z",
        "proposed_patch": {
            "operation": "replace_item_content", "category": "question_total_mismatch",
            "affected_id": "2", "target_id": "2.1", "replacement_id": "2.1",
            "printed_marks": 1, "expected_total": 1,
            "mark_points": [{"count": 1, "code": "A", "descriptor": "35.9", "source": "1A 35.9"}],
            "reconciliation_scope": "suspicious_child",
        },
    }
    restore = {
        "id": "restore-21", "confirmation_status": "confirmed", "confirmed_at": "2026-10-19T09:00:00Z",
        "proposed_patch": {
            "operation": "withdraw_confirmed_correction", "category": "question_total_mismatch",
            "affected_id": "2.1", "target_id": "2.1", "supersedes_correction_id": "old-21",
            "supersession_reason": "teacher_restored_source_state", "source_restoration": True,
            "reconciliation_scope": "suspicious_child",
        },
    }
    result, applied, issues = apply_confirmed_corrections(structure, {}, [old, restore])
    assert issues == []
    assert [item["operation"] for item in applied] == ["withdraw_confirmed_correction"]
    q21 = next(q for q in result["questions"] if q["question_id"] == "2.1")
    assert q21["computed_shorthand_marks"] == 0
    assert q21["mark_points"] == []
    children = {q["question_id"]: q["computed_shorthand_marks"] for q in result["questions"] if q["question_id"] != "2.1"}
    assert children == {"2.1.1": 1, "2.1.2": 1, "2.2": 2, "2.3": 2, "2.4": 3}
    assert sum(children.values()) == 9
    _, history = effective_correction_history([old, restore])
    assert history[0]["effective"] is False
    assert history[0]["superseded_by"] == "restore-21"
    assert history[0]["supersession_reason"] == "teacher_restored_source_state"
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


def test_question_workspace_restoration_returns_parent_to_source_and_totals_children():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    child = _section("CHILD REPAIR MODEL")
    support = r"""
function majorQuestionId(value){const match=String(value||'').match(/^\d+/);return match?match[0]:''}
"""
    program = dependency + support + child + r"""
const x=JSON.parse(process.argv[1]);
const model=questionLedgerModel(x.structure,x.exceptions,x.staged,'2');
console.log(JSON.stringify({projected:model.projected_total,effective:effectiveStagedCorrections(x.staged).map(item=>item.id),rows:model.rows.map(row=>({id:row.question_id,total:row.projected,staged:row.staged}))}));
"""
    questions = [_question("2.1", 1, 0), _question("2.1.1", 2, 1), _question("2.1.2", 3, 1),
                 _question("2.2", 4, 2), _question("2.3", 5, 2), _question("2.4", 6, 3)]
    questions[0].update({"printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []})
    result = _node(program, {
        "structure": {"questions": questions},
        "exceptions": [{"id": "parent", "category": "question_total_mismatch", "affected_id": "2", "message": "Question 2 observed subtotal 9 does not equal computed 10."}],
        "staged": [
            {"id": "old", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "affected_id": "2", "target_id": "2.1", "expected_total": 1}},
            {"id": "restore", "confirmation_status": "confirmed", "proposed_patch": {"operation": "withdraw_confirmed_correction", "affected_id": "2.1", "target_id": "2.1", "supersedes_correction_id": "old", "source_restoration": True}},
        ],
    })
    assert result["effective"] == []
    assert result["projected"] == 9
    assert result["rows"][0] == {"id": "2.1", "total": 0, "staged": True}


def test_applied_q52_correction_is_editable_and_source_occurrence_bound():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    program = dependency + r"""
const x=JSON.parse(process.argv[1]);
const found=effectiveCorrectionForQuestion(x.question,x.history,x.questions);
const wrongOccurrence=effectiveCorrectionForQuestion(x.other,x.history,x.questions);
const ambiguous=effectiveCorrectionForQuestion(x.duplicate,x.unlocated,x.duplicateQuestions);
console.log(JSON.stringify({id:found?.id||null,applied:found?.applied_at||null,wrong:wrongOccurrence?.id||null,ambiguous:ambiguous?.id||null}));
"""
    history = [{
        "id": "bbcefbbd-5281-4400-b26a-cd485a5e4b0f",
        "confirmation_status": "confirmed",
        "applied_at": "2026-10-20T09:27:32Z",
        "proposed_patch": {
            "operation": "replace_item_content", "target_id": "5.2",
            "replacement_id": "5.2", "source_block_index": 3, "expected_total": 2,
        },
    }]
    result = _node(program, {
        "question": {"question_id": "5.2", "source_block_index": 3},
        "other": {"question_id": "5.2", "source_block_index": 8},
        "questions": [
            {"question_id": "5.2", "source_block_index": 3},
            {"question_id": "5.2", "source_block_index": 8},
        ],
        "history": history,
        "duplicate": {"question_id": "5.2", "source_block_index": 3},
        "duplicateQuestions": [
            {"question_id": "5.2", "source_block_index": 3},
            {"question_id": "5.2", "source_block_index": 8},
        ],
        "unlocated": [{
            **history[0],
            "id": "legacy-unlocated",
            "proposed_patch": {k: v for k, v in history[0]["proposed_patch"].items() if k != "source_block_index"},
        }],
    })
    assert result == {
        "id": "bbcefbbd-5281-4400-b26a-cd485a5e4b0f",
        "applied": "2026-10-20T09:27:32Z",
        "wrong": None,
        "ambiguous": None,
    }


def test_q5_applied_history_restores_structural_parent_and_projects_twelve_immediately():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    child = _section("CHILD REPAIR MODEL")
    support = r"""
function majorQuestionId(value){const match=String(value||'').match(/^\d+/);return match?match[0]:''}
"""
    program = dependency + support + child + r"""
const x=JSON.parse(process.argv[1]);
const before=questionLedgerModel(x.structure,x.exceptions,x.stagedBefore,'5',x.historyBefore);
const after=questionLedgerModel(x.structure,x.exceptions,x.stagedAfter,'5',x.historyAfter);
const q52Before=before.rows.find(row=>row.question_id==='5.2');
const q52After=after.rows.find(row=>row.question_id==='5.2');
console.log(JSON.stringify({
 beforeTotal:before.projected_total,
 afterTotal:after.projected_total,
 previousId:q52Before.staged_correction_id,
 previousApplied:q52Before.correction_applied,
 sourceRestorable:!sourceQuestionHasDirectMarks(x.structure.questions.find(q=>q.question_id==='5.2')),
 afterRows:after.rows.map(row=>({id:row.question_id,total:row.projected,corrected:row.staged})),
 q52AfterCorrected:q52After.staged,
}));
"""
    questions = [_question("5.1", 3, 0), _question("5.2", 3, 0), _question("5.2.1", 3, 0), _question("5.2.2", 3, 0)]
    for question in questions:
        question.update({"printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []})

    def correction(identifier: str, target: str, total: int, *, applied: bool = True) -> dict:
        return {
            "id": identifier, "confirmation_status": "confirmed",
            "applied_at": "2026-10-20T09:27:32Z" if applied else None,
            "proposed_patch": {
                "operation": "replace_item_content", "target_id": target,
                "replacement_id": target, "source_block_index": 3,
                "expected_total": total,
                "mark_points": [{"count": total, "code": "A", "descriptor": target, "source": f"{total}A {target}"}],
            },
        }

    q51 = correction("q51-applied", "5.1", 8)
    q52 = correction("bbcefbbd-5281-4400-b26a-cd485a5e4b0f", "5.2", 2)
    q522 = correction("q522-applied", "5.2.2", 2)
    q521 = correction("q521-staged", "5.2.1", 2, applied=False)
    restore = {
        "id": "q52-restore", "confirmation_status": "confirmed", "applied_at": None,
        "proposed_patch": {
            "operation": "withdraw_confirmed_correction", "target_id": "5.2",
            "affected_id": "5.2", "source_block_index": 3,
            "supersedes_correction_id": q52["id"], "source_restoration": True,
        },
    }
    exceptions = [{"id": "q5-parent", "category": "question_total_mismatch", "affected_id": "5", "message": "Question 5 observed subtotal 12 does not equal computed 0."}]
    result = _node(program, {
        "structure": {"questions": questions}, "exceptions": exceptions,
        "stagedBefore": [q521], "historyBefore": [q51, q52, q522, q521],
        "stagedAfter": [q521, restore], "historyAfter": [q51, q52, q522, q521, restore],
    })
    assert result["beforeTotal"] == 14
    assert result["previousId"] == q52["id"]
    assert result["previousApplied"] is True
    assert result["sourceRestorable"] is True
    assert result["afterTotal"] == 12
    assert result["afterRows"] == [
        {"id": "5.1", "total": 8, "corrected": True},
        {"id": "5.2", "total": 0, "corrected": True},
        {"id": "5.2.1", "total": 2, "corrected": True},
        {"id": "5.2.2", "total": 2, "corrected": True},
    ]
    assert result["q52AfterCorrected"] is True


def test_q5_source_restoration_replay_is_idempotent_and_preserves_children():
    structure = {"questions": [_question("5.1", 3, 0), _question("5.2", 3, 0), _question("5.2.1", 3, 0), _question("5.2.2", 3, 0)], "exceptions": [], "summary": {}}
    for question in structure["questions"]:
        question.update({"printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []})
    old = {
        "id": "old-q52", "confirmation_status": "confirmed", "applied_at": "2026-10-20T09:27:32Z",
        "proposed_patch": {"operation": "replace_item_content", "target_id": "5.2", "replacement_id": "5.2", "source_block_index": 3, "expected_total": 2, "mark_points": [{"count": 2, "code": "A", "descriptor": "wrong", "source": "2A wrong"}]},
    }
    restore = {
        "id": "restore-q52", "confirmation_status": "confirmed",
        "proposed_patch": {"operation": "withdraw_confirmed_correction", "target_id": "5.2", "affected_id": "5.2", "source_block_index": 3, "supersedes_correction_id": "old-q52", "source_restoration": True, "supersession_reason": "teacher_restored_source_state"},
    }
    q521 = {
        "id": "q521", "confirmation_status": "confirmed",
        "proposed_patch": {"operation": "replace_item_content", "target_id": "5.2.1", "replacement_id": "5.2.1", "source_block_index": 3, "solution_lines": ["Correct child answer"], "expected_total": 2, "mark_points": [{"count": 2, "code": "A", "descriptor": "child", "source": "2A child"}]},
    }
    first, _, issues = apply_confirmed_corrections(structure, {}, [old, restore, q521])
    second, _, second_issues = apply_confirmed_corrections(structure, {}, [old, restore, q521])
    assert issues == second_issues == []
    assert first == second
    assert [q["question_id"] for q in first["questions"]] == ["5.1", "5.2", "5.2.1", "5.2.2"]
    q52 = next(q for q in first["questions"] if q["question_id"] == "5.2")
    q521_result = next(q for q in first["questions"] if q["question_id"] == "5.2.1")
    assert q52["computed_shorthand_marks"] == 0 and q52["mark_points"] == []
    assert q521_result["computed_shorthand_marks"] == 2
    assert old["applied_at"] == "2026-10-20T09:27:32Z"


def test_q5_corrected_current_structure_uses_immutable_source_for_restoration_projection():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    child = _section("CHILD REPAIR MODEL")
    support = r"""
function majorQuestionId(value){const match=String(value||'').match(/^\d+/);return match?match[0]:''}
"""
    program = dependency + support + child + r"""
const x=JSON.parse(process.argv[1]);
const immutable=new Map(Object.entries(x.immutable));
const before=questionLedgerModel(x.structure,x.exceptions,x.stagedBefore,'5',x.historyBefore,immutable);
const after=questionLedgerModel(x.structure,x.exceptions,x.stagedAfter,'5',x.historyAfter,immutable);
const currentQ52=x.structure.questions.find(q=>q.question_id==='5.2');
const originalQ52=immutable.get('5.2@3');
console.log(JSON.stringify({
 currentQ52Total:currentQ52.computed_shorthand_marks,
 immutableQ52Direct:originalQ52.has_direct_marks,
 sourceRestorable:!sourceQuestionHasDirectMarks(originalQ52),
 beforeTotal:before.projected_total,
 afterTotal:after.projected_total,
 documentTotal:38+after.projected_total,
 afterRows:after.rows.map(row=>({id:row.question_id,total:row.projected,correction:row.staged_correction_id})),
}));
"""
    def question(identifier: str, total: int) -> dict:
        return {
            "question_id": identifier, "source_block_index": 3,
            "printed_marks": total or None, "computed_shorthand_marks": total,
            "mark_points": [] if not total else [{"count": total, "code": "A", "source": f"{total}A corrected"}],
        }
    structure = {"questions": [question("5.1", 8), question("5.2", 2), question("5.2.1", 2), question("5.2.2", 2)]}
    immutable = {
        "5.1@3": {**question("5.1", 0), "has_direct_marks": False, "structural_parent": False},
        "5.2@3": {**question("5.2", 0), "has_direct_marks": False, "structural_parent": True},
        "5.2.1@3": {**question("5.2.1", 0), "has_direct_marks": False, "structural_parent": False},
        "5.2.2@3": {**question("5.2.2", 0), "has_direct_marks": False, "structural_parent": False},
    }
    def correction(identifier: str, target: str, total: int, applied: bool = True) -> dict:
        return {"id": identifier, "confirmation_status": "confirmed", "applied_at": "2026-10-20T09:27:32Z" if applied else None,
                "proposed_patch": {"operation": "replace_item_content", "target_id": target, "replacement_id": target,
                                   "source_block_index": 3, "expected_total": total,
                                   "mark_points": [{"count": total, "code": "A", "source": f"{total}A {target}"}]}}
    q51 = correction("q51", "5.1", 8)
    q52 = correction("bbcefbbd-5281-4400-b26a-cd485a5e4b0f", "5.2", 2)
    q521 = correction("q521", "5.2.1", 2, False)
    q522 = correction("q522", "5.2.2", 2)
    restore = {"id": "q52-restore", "confirmation_status": "confirmed", "applied_at": None,
               "proposed_patch": {"operation": "withdraw_confirmed_correction", "target_id": "5.2",
                                  "affected_id": "5.2", "source_block_index": 3,
                                  "supersedes_correction_id": q52["id"], "source_restoration": True}}
    result = _node(program, {
        "structure": structure, "immutable": immutable,
        "exceptions": [{"id": "q5", "category": "question_total_mismatch", "affected_id": "5", "message": "subtotal 12"}],
        "stagedBefore": [q521], "historyBefore": [q51, q52, q521, q522],
        "stagedAfter": [q521, restore], "historyAfter": [q51, q52, q521, q522, restore],
    })
    assert result == {
        "currentQ52Total": 2, "immutableQ52Direct": False, "sourceRestorable": True,
        "beforeTotal": 14, "afterTotal": 12, "documentTotal": 50,
        "afterRows": [
            {"id": "5.1", "total": 8, "correction": "q51"},
            {"id": "5.2", "total": 0, "correction": "q52-restore"},
            {"id": "5.2.1", "total": 2, "correction": "q521"},
            {"id": "5.2.2", "total": 2, "correction": "q522"},
        ],
    }


def test_q5_restoration_controls_use_immutable_source_and_offer_overwrite():
    page = PAGE.read_text(encoding="utf-8")
    assert "immutableSourceStateForQuestionOccurrence(await ensureNormalized()" in page
    assert "immutableSourceStateForQuestionOccurrence(normalized,question.question_id,question.source_block_index)" in page
    assert "Edit / overwrite correction" in page
    assert "Restore original memo state" in page
    assert "Original memo state: structural question with no direct mark allocation" in page
    assert "sourceQuestionHasDirectMarks(question)" not in page


def test_source_mark_detection_allows_only_unmarked_structural_source():
    child = _section("CHILD REPAIR MODEL")
    program = child + r"""
const x=JSON.parse(process.argv[1]);
console.log(JSON.stringify(x.map(sourceQuestionHasDirectMarks)));
"""
    result = _node(program, [
        {"question_id": "2.1", "printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []},
        {"question_id": "2.2", "printed_marks": 2, "computed_shorthand_marks": 2, "mark_points": []},
        {"question_id": "2.3", "printed_marks": None, "computed_shorthand_marks": 0, "mark_points": [{"count": 1}]},
    ])
    assert result == [False, True, True]


def test_restoration_showback_is_teacher_facing_and_contains_no_zero_mark_scheme():
    showback = _section("TEACHER SHOWBACK MODEL")
    program = showback + r"""
const x=JSON.parse(process.argv[1]);
console.log(JSON.stringify(teacherShowBackModel(x)));
"""
    result = _node(program, {
        "display_text": "Question 2.1: restore the original memo state.",
        "proposed_patch": {
            "operation": "withdraw_confirmed_correction", "target_id": "2.1",
            "source_restoration": True, "supersedes_correction_id": "old-21",
            "previous_expected_total": 1,
            "previous_mark_points": [{"count": 1, "code": "A", "descriptor": "35.9"}],
        },
    })
    assert result["source_restoration"] is True
    assert result["expected_total"] is None
    assert result["mark_points"] == []
    assert result["previous_mark_points"] == [{"count": 1, "code": "A", "descriptor": "35.9"}]


def test_parent_overlay_reconciles_against_effective_staged_children():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    child = _section("CHILD REPAIR MODEL")
    support = r"""
function majorQuestionId(value){const match=String(value||'').match(/^\d+/);return match?match[0]:''}
"""
    program = dependency + support + child + r"""
const x=JSON.parse(process.argv[1]);
console.log(JSON.stringify(effectiveParentOverlay(x.structure,x.exceptions,x.staged,x.major)));
"""
    q1 = {
        "major": "1",
        "structure": {"questions": [_question("1.1", 1, 0), _question("1.2", 2, 0)]},
        "exceptions": [{"id": "parent-1", "category": "question_total_mismatch", "affected_id": "1", "message": "Question 1 observed subtotal 7 does not equal computed 0."}],
        "staged": [
            {"id": "one", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": "1.1", "expected_total": 4}},
            {"id": "old", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": "1.2", "expected_total": 4}},
            {"id": "new", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": "1.2", "expected_total": 3, "supersedes_correction_id": "old"}},
            {"id": "pending", "confirmation_status": "pending", "proposed_patch": {"operation": "replace_item_content", "target_id": "1.2", "expected_total": 9}},
            {"id": "rejected", "confirmation_status": "rejected", "proposed_patch": {"operation": "replace_item_content", "target_id": "1.1", "expected_total": 8}},
        ],
    }
    q3 = {
        "major": "3",
        "structure": {"questions": [_question("3.1", 3, 0), _question("3.2", 4, 0), _question("3.3", 5, 0)]},
        "exceptions": [{"id": "parent-3", "category": "question_total_mismatch", "affected_id": "3", "message": "Question 3 observed subtotal 9 does not equal computed 0."}],
        "staged": [
            {"id": "31", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": "3.1", "expected_total": 3}},
            {"id": "32", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": "3.2", "expected_total": 2}},
            {"id": "33", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": "3.3", "expected_total": 2}},
        ],
    }
    one = _node(program, q1)
    three = _node(program, q3)
    assert (one["source_subtotal"], one["original_converter_total"], one["effective_staged_total"], one["difference"]) == ("7", 0, 7, 0)
    assert (three["source_subtotal"], three["original_converter_total"], three["effective_staged_total"], three["difference"]) == ("9", 0, 7, 2)


def test_parent_reconciliation_uses_shared_overlay_and_server_recomputation():
    page = PAGE.read_text(encoding="utf-8")
    submit = SUBMIT.read_text(encoding="utf-8")
    assert "Original converter total" in page
    assert "Current staged child total" in page
    assert "The memo total is wrong — use ${esc(effective)}" in page
    assert "parent_reconciliation:{choice:'source_wrong',effective_total:Number(effective)}" in page
    assert "No child marks will change." in page
    assert 'function effectiveChildTotal(' in submit
    assert '.eq("confirmation_status", "confirmed").is("applied_at", null)' in submit
    assert 'correctionQuery.gte("confirmed_at", job.started_at)' in submit
    assert 'error: "stale_review_state"' in submit
    assert "submittedEffectiveTotal !== serverEffectiveTotal" in submit
    assert "Number(match[1]) !==" not in submit


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
    assert "The current effective correction is loaded below" in page
    assert "Replace the currently staged correction for Question" in page
    assert "Previous staged total" in page
    assert "New staged total" in page
    assert "Continue pending correction" in page
    assert "Edit pending correction" in page
    assert "Pending — not saved" in page
    assert "Restore original memo state" in page
    assert "restore_source_state:restorationRequested" in page
    assert "no direct mark allocation" in page
    assert "The earlier saved correction remains in the audit trail" in page
    assert "its child questions remain unchanged" in page


def test_edge_contracts_validate_amendment_manual_context_and_duplicate_occurrence():
    submit = SUBMIT.read_text(encoding="utf-8")
    confirm = CONFIRM.read_text(encoding="utf-8")
    assert 'error: "ambiguous_numbering_source"' in submit
    assert "source_block_index: selectedSourceIndex" in submit
    assert 'source_locator: {' in submit
    assert 'source_line_hash: selectedLineHash' in submit
    assert 'original_source_block_index: selectedSourceIndex' in submit
    assert 'supersession_reason: "teacher_amended_previous_change"' in submit
    assert "correctionPredecessorMatchesSource" in submit
    child_repair = submit.split('} else if (childRepair && typeof childRepair === "object") {', 1)[1].split('} else if (contentCorrection', 1)[0]
    prior_guard = child_repair.split('if (supersedesCorrectionId) {', 1)[1].split('const { data: confirmedRows', 1)[0]
    assert "prior.applied_at" not in prior_guard
    assert "priorOccurrenceMatches" in prior_guard
    assert 'String(row.proposed_patch?.supersedes_correction_id ?? "") === supersedesCorrectionId' in submit
    assert 'error: "invalid_source_restoration"' in submit
    assert 'operation: "withdraw_confirmed_correction"' in submit
    assert 'source_restoration: true' in submit
    assert 'reconciliation_scope: teacherInitiated ? "teacher_initiated_item"' in submit
    assert 'correction_scope: teacherInitiated ? "teacher_initiated_item"' in submit
    assert 'patch.correction_scope === "teacher_initiated_item"' in confirm
    assert "other.source_block_index" in confirm


def test_occurrence_review_uses_teacher_facing_page_and_parent_context():
    page = PAGE.read_text(encoding="utf-8")
    assert "— Question ${heading||'?'} — ${where}" in page
    assert "selectedNumberingOccurrence()" in page
    assert "sourcePageForException(currentException,structure,normalized,occurrence)" in page
    assert "candidates=candidates.filter(candidate=>candidate.page===occurrencePage)" in page
    assert "source block ${question?.source_block_index}" not in page


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
