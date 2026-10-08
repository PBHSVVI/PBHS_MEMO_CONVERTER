from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.src.memo_engine.semantic import build_semantic_plan, interpret_semantics
from engine.src.memo_engine.cli import _try_reuse_semantic
from engine.src.memo_engine.phase7_5 import apply_phase7_5_patch
from engine.src.memo_engine.structure import parse_mark_points
from engine.src.memo_engine.teacher_language import TeacherLanguageError, ai_result_to_proposal

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


def _section(name: str) -> str:
    match = re.search(rf"// BEGIN {name}\s*(.*?)\s*// END {name}", PAGE.read_text(encoding="utf-8"), re.S)
    assert match
    return match.group(1)


def _node(program: str, value: object) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    run = subprocess.run([node, "--input-type=module", "-e", program, json.dumps(value)], check=True, capture_output=True, text=True)
    return json.loads(run.stdout)


def test_queue_uses_natural_numeric_question_order():
    model = _section("REVIEW DEPENDENCY MODEL")
    items = [
        {"id": "a", "category": "item_total_mismatch", "affected_id": "10.2"},
        {"id": "b", "category": "item_total_mismatch", "affected_id": "2"},
        {"id": "c", "category": "item_total_mismatch", "affected_id": "10.1"},
        {"id": "d", "category": "item_total_mismatch", "affected_id": "1.1.2"},
        {"id": "e", "category": "item_total_mismatch", "affected_id": "1.1.1"},
    ]
    result = _node(model + "\nconst s=reconcileReviewQueue(JSON.parse(process.argv[1]),{});console.log(JSON.stringify(s.items.map(x=>x.affected_id)));", items)
    assert result == ["1.1.1", "1.1.2", "2", "10.1", "10.2"]


def test_dependency_still_overrides_natural_order():
    model = _section("REVIEW DEPENDENCY MODEL")
    items = [
        {"id": "parent", "category": "question_total_mismatch", "affected_id": "3"},
        {"id": "child", "category": "item_total_mismatch", "affected_id": "3.1"},
        {"id": "later", "category": "item_total_mismatch", "affected_id": "4.1"},
    ]
    result = _node(model + "\nconsole.log(JSON.stringify(actionableReviewQueue(JSON.parse(process.argv[1])).map(x=>x.id)));", items)
    assert result == ["child", "later"]


def test_skip_survives_recreated_exception_uuid_by_logical_key():
    model = _section("REVIEW DEPENDENCY MODEL")
    first = [
        {"id": "old", "category": "item_total_mismatch", "affected_id": "5.1.1"},
        {"id": "other", "category": "item_total_mismatch", "affected_id": "5.1.2"},
    ]
    recreated = [
        {"id": "new", "category": "item_total_mismatch", "affected_id": "5.1.1"},
        {"id": "other-new", "category": "item_total_mismatch", "affected_id": "5.1.2"},
    ]
    program = model + "\nconst a=JSON.parse(process.argv[1]);let s=reconcileReviewQueue(a.first,{});s=skipReviewQueue(s);s=reconcileReviewQueue(a.recreated,s);console.log(JSON.stringify({order:s.items.map(x=>x.id),skipped:s.skipped_keys}));"
    result = _node(program, {"first": first, "recreated": recreated})
    assert result["order"] == ["other-new", "new"]
    assert result["skipped"] == ["item_total_mismatch|5.1.1||"]


def test_source_focus_rejects_q3_q6_numeric_collisions():
    source = _section("SOURCE FOCUS MODEL")
    blocks = [
        {"cells": ["Question 1.4", "Use 6 in the calculation", "(3)"], "combined": "Question 1.4 Use 6 (3)"},
        {"cells": ["6", "Geometry result", "[20]"], "combined": "6 Geometry result [20]"},
        {"cells": ["3.1", "Solve", "(4)"], "combined": "3.1 Solve (4)"},
    ]
    program = "const textMatches=(a,b)=>String(a).includes(String(b));\n" + source + "\nconst b=JSON.parse(process.argv[1]);console.log(JSON.stringify({q6:b.map(x=>sourceBlockMatches(x,'6',false,true)),q31:b.map(x=>sourceBlockMatches(x,'3.1',false,true))}));"
    result = _node(program, blocks)
    assert result == {"q6": [False, True, False], "q31": [False, False, True]}



def test_split_run_question_label_wins_over_nested_numeric_span():
    source = _section("SOURCE FOCUS MODEL")
    program = r"""
const textMatches=(a,b)=>String(a).includes(String(b));
""" + source + r"""
const span={textContent:'3.2'};
const paragraph={textContent:'3.2 Determine the line relationship'};
let selector='';
const root={querySelectorAll(value){selector=value;return value==='p,td,th'?[paragraph]:[span,paragraph]}};
const found=findTokenElement(root,'3.2',false,true);
console.log(JSON.stringify({selector,paragraph:found===paragraph,span:found===span}));
"""
    result = _node(program, {})
    assert result == {"selector": "p,td,th", "paragraph": True, "span": False}


def test_structural_question_region_precedes_global_token_fallback():
    html = PAGE.read_text(encoding="utf-8")
    focused = html.split("async function renderFocusedEvidence()", 1)[1].split(
        "function renderFullMemo", 1
    )[0]
    assert "Number.isInteger(currentStep?.sourceBlockIndex)?visibleQuestionRegion" in focused
    assert "made=structural||visibleCloneAround(currentStep)" in focused


def test_geometry_conflict_uses_content_editor_without_ledger_edit_controls():
    model = _section("BOUNDED EDITOR MODEL")
    program = (
        "function majorQuestionId(value){const m=String(value||'').match(/^\\\\d+/);"
        "return m?m[0]:''}\n" + model
        + "\nconst cases=JSON.parse(process.argv[1]);"
        + "\nconsole.log(JSON.stringify(cases.map(x=>boundedItemEditorAllowed(x.ex,x.target))));"
    )
    cases = [
        {"ex": {"category": "geometry_line_relationship_conflict", "affected_id": "3.2"}, "target": "3.1"},
        {"ex": {"category": "geometry_line_relationship_conflict", "affected_id": "3.2"}, "target": "3.2"},
        {"ex": {"category": "item_total_mismatch", "affected_id": "3.2"}, "target": "3.1"},
        {"ex": {"category": "item_total_mismatch", "affected_id": "3.2"}, "target": "3.2"},
        {"ex": {"category": "question_total_mismatch", "affected_id": "3"}, "target": "3.1"},
    ]
    assert _node(program, cases) == [False, False, False, True, True]
    html = PAGE.read_text(encoding="utf-8")
    assert "setCorrectionTool(ex.category==='question_total_mismatch'?'typed':'content')" in html
    assert "row.inserted||!boundedItemEditorAllowed(ex,row.question_id)" in html

def test_long_processing_has_no_fixed_timeout_and_remains_resumable():
    html = PAGE.read_text(encoding="utf-8")
    assert "for(let i=0;i<300" not in html
    assert "Timed out waiting for Phase 7.5 revalidation" not in html
    assert "Taking a little longer than usual — still working" in html
    assert "You can close this page. Your work is saved." in html
    assert "['failed','failed_retryable'].includes(j.status)" in html
    assert "monitorProcessing()" in html


def test_source_focus_prefers_structural_block_provenance():
    html = PAGE.read_text(encoding="utf-8")
    assert "sourceBlockFor(ex,structure)" in html
    assert "sourceBlockIndex:sourceBlockFor(ex,structure)" in html
    assert "Number.isInteger(step.sourceBlockIndex)" in html


def test_parent_total_reconciliation_is_ledger_driven():
    html = PAGE.read_text(encoding="utf-8")
    edge = (ROOT / "supabase" / "functions" / "submit-correction" / "index.ts").read_text(encoding="utf-8")
    assert "The memo total is wrong" in html
    assert "The memo total is correct — check a subquestion" in html
    assert "deterministic_parent_ledger" in edge
    assert "invalid_parent_reconciliation" in edge


def test_question_workspace_and_staged_batch_preserve_individual_corrections():
    html = PAGE.read_text(encoding="utf-8")
    edge = (ROOT / "supabase" / "functions" / "confirm-correction" / "index.ts").read_text(encoding="utf-8")
    assert 'id="questionWorkspace"' in html
    assert "Total after your changes" in html
    assert "Saved changes keep their own audit history" in html
    assert "Review this item" in html
    assert 'id="applyBatch"' in html
    assert "defer_revalidation:true" in html
    assert 'id="confirmApply"' not in html
    assert "phase8_correction_staged" in edge
    assert "conflicting_staged_correction" in edge


def _child_ledger(value: object) -> object:
    model = _section("CHILD REPAIR MODEL")
    helpers = """
function majorQuestionId(value){const match=String(value||'').match(/^\\d+/);return match?match[0]:''}
function compareQuestionIds(a,b){const aa=String(a).split('.').map(Number),bb=String(b).split('.').map(Number),n=Math.max(aa.length,bb.length);for(let i=0;i<n;i++){const d=(aa[i]??-1)-(bb[i]??-1);if(d)return d}return 0}
function isDependent(){return false}
function parentDiscrepancyDetails(parent){const values=String(parent.message||'').match(/\\d+/g)||[];return {source_total:values.at(-2)||null,converter_total:values.at(-1)||null}}
"""
    program = helpers + model + "\nconst x=JSON.parse(process.argv[1]);console.log(JSON.stringify(questionLedgerModel(x.structure,x.exceptions,x.staged,x.major)));"
    return _node(program, value)


def test_parent_mismatch_makes_zero_mark_child_without_exception_actionable():
    result = _child_ledger({
        "major": "3",
        "structure": {"questions": [
            {"question_id": "3.1", "printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []},
            {"question_id": "3.1.2", "printed_marks": 4, "computed_shorthand_marks": 4, "mark_points": [{"count": 4}]},
            {"question_id": "3.1.3", "printed_marks": 4, "computed_shorthand_marks": 4, "mark_points": [{"count": 4}]},
            {"question_id": "3.1.4", "printed_marks": 4, "computed_shorthand_marks": 4, "mark_points": [{"count": 4}]},
        ]},
        "exceptions": [{"id": "parent", "category": "question_total_mismatch", "affected_id": "3", "message": "source subtotal 14; computed total 12"}],
        "staged": [],
    })
    first = result["rows"][0]
    assert first["question_id"] == "3.1"
    assert first["exception_id"] is None
    assert any(reason.startswith("Possible missing child allocation") for reason in first["suspicion_reasons"])
    assert any(reason.startswith("Numbering sequence may be incomplete") for reason in first["suspicion_reasons"])
    assert first["projected_id"] == "3.1"  # inspection never auto-renames


def test_staged_child_repair_projects_parent_balance_before_revalidation():
    value = {
        "major": "3",
        "structure": {"questions": [
            {"question_id": "3.1", "printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []},
            {"question_id": "3.1.2", "printed_marks": 4, "computed_shorthand_marks": 4, "mark_points": [{"count": 4}]},
            {"question_id": "3.1.3", "printed_marks": 4, "computed_shorthand_marks": 4, "mark_points": [{"count": 4}]},
            {"question_id": "3.1.4", "printed_marks": 4, "computed_shorthand_marks": 4, "mark_points": [{"count": 4}]},
        ]},
        "exceptions": [{"id": "parent", "category": "question_total_mismatch", "affected_id": "3", "message": "source subtotal 14; computed total 12"}],
        "staged": [{"proposed_patch": {"operation": "replace_item_content", "target_id": "3.1", "replacement_id": "3.1.1", "expected_total": 2}}],
    }
    result = _child_ledger(value)
    assert result["computed_total"] == 12
    assert result["projected_total"] == 14
    assert int(result["source_total"]) - result["projected_total"] == 0
    assert result["rows"][0]["projected_id"] == "3.1.1"
    assert result["rows"][0]["staged"] is True
    assert result["rows"][0]["suspicion_reasons"] == []


def test_healthy_child_without_exception_remains_editable_without_warning():
    result = _child_ledger({
        "major": "4",
        "structure": {"questions": [
            {"question_id": "4.1", "printed_marks": 2, "computed_shorthand_marks": 2, "mark_points": [{"count": 2}]},
            {"question_id": "4.2", "printed_marks": 3, "computed_shorthand_marks": 3, "mark_points": [{"count": 3}]},
        ]},
        "exceptions": [{"id": "parent", "category": "question_total_mismatch", "affected_id": "4", "message": "source subtotal 5; computed total 5"}],
        "staged": [],
    })
    assert all(not row["suspicion_reasons"] for row in result["rows"])


def test_child_rename_and_marks_apply_atomically():
    structure = {
        "questions": [{"question_id": "3.1", "path": [3, 1], "depth": 2, "source_block_index": 10, "printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []}],
        "exceptions": [{"category": "question_total_mismatch", "affected_id": "3"}],
    }
    patch = {
        "operation": "replace_item_content", "category": "question_total_mismatch", "affected_id": "3",
        "target_id": "3.1", "replacement_id": "3.1.1", "printed_marks": 2, "expected_total": 2,
        "mark_points": [
            {"count": 1, "code": "A", "descriptor": "x-coordinate of M", "source": "1A x-coordinate of M"},
            {"count": 1, "code": "A", "descriptor": "y-coordinate of M", "source": "1A y-coordinate of M"},
        ],
        "question_text": None, "solution_lines": [], "reconciliation_scope": "suspicious_child",
    }
    applied, issue, handled = apply_phase7_5_patch(structure, {}, correction_id="corr", category="question_total_mismatch", affected_id="3", operation="replace_item_content", patch=patch)
    assert handled and issue is None
    assert applied["identifier_replaced"] is True
    question = structure["questions"][0]
    assert question["question_id"] == "3.1.1"
    assert question["source_question_id"] == "3.1"
    assert question["printed_marks"] == question["computed_shorthand_marks"] == 2
    assert len(question["mark_points"]) == 2
    assert structure["exceptions"] == []


def test_invalid_child_marks_do_not_leave_half_rename():
    structure = {
        "questions": [{"question_id": "3.1", "path": [3, 1], "depth": 2, "source_block_index": 10, "printed_marks": None, "computed_shorthand_marks": 0, "mark_points": []}],
        "exceptions": [{"category": "question_total_mismatch", "affected_id": "3"}],
    }
    original = json.loads(json.dumps(structure))
    patch = {
        "operation": "replace_item_content", "category": "question_total_mismatch", "affected_id": "3",
        "target_id": "3.1", "replacement_id": "3.1.1", "printed_marks": 2, "expected_total": 2,
        "mark_points": [{"count": 1, "code": "A", "descriptor": "x-coordinate", "source": "1A x-coordinate"}],
        "question_text": None, "solution_lines": [], "reconciliation_scope": "suspicious_child",
    }
    applied, issue, handled = apply_phase7_5_patch(structure, {}, correction_id="corr", category="question_total_mismatch", affected_id="3", operation="replace_item_content", patch=patch)
    assert handled and applied is None
    assert issue["category"] == "correction_mark_total_invalid"
    assert structure == original


def test_child_repair_stays_confirmation_gated_and_auditable():
    html = PAGE.read_text(encoding="utf-8")
    submit = (ROOT / "supabase" / "functions" / "submit-correction" / "index.ts").read_text(encoding="utf-8")
    confirm = (ROOT / "supabase" / "functions" / "confirm-correction" / "index.ts").read_text(encoding="utf-8")
    assert ">Edit</button>" in html
    assert "Add a missing subquestion" in html
    assert "Review this correction" in html
    assert "SHOW-BACK — not applied yet" in html
    assert 'id="confirm"' in html
    assert 'reconciliation_scope: parentReview ? "suspicious_child" : "bounded_item_editor"' in submit
    assert 'operation: "insert_missing_child_question"' in submit
    assert 'reconciliation_scope: "missing_child"' in submit
    assert 'exceptionStatus = "awaiting_confirmation"' in submit
    assert "parent_review_retained" in confirm
    assert "retainParentReview" in confirm


def test_sr_aliases_are_one_combined_mark():
    for source in ["1SR statement and reason", "1S/R statement and reason", "1S-R statement and reason"]:
        points = parse_mark_points(source)
        assert len(points) == 1
        assert points[0]["count"] == 1
        assert points[0]["code"] == "S/R"
        assert points[0]["semantic"] == "statement_reason"


def test_unrelated_semantic_candidate_is_reused_while_changed_candidate_runs():
    structure = {"job_id": "job", "questions": [{"question_id": "7.2", "source_preview": "Trigonometry", "mark_points": [
        {"count": 1, "code": "A", "descriptor": "first value", "notation": "shorthand", "semantic": "accuracy"},
        {"count": 1, "code": "A", "descriptor": "changed value", "notation": "shorthand", "semantic": "accuracy"},
    ]}]}
    cached = [{"candidate_id": "7_2__m1", "question_id": "7.2", "mark_index": 0, "count": 1, "source_shorthand": "A", "descriptor": "first value", "source_notation": "shorthand", "source_semantic": "accuracy", "semantic_type": "accuracy", "confidence_score": .99, "band": "green", "provider_valid": True, "resolution_method": "groq:model"}]
    def fake(candidates, **kwargs):
        return ([{**c, "semantic_type": "accuracy", "confidence_score": .99, "band": "green", "rationale": "fresh", "provider_valid": True, "provider_validation_issue": None, "resolution_method": "test"} for c in candidates], [])
    with patch("engine.src.memo_engine.semantic._run_batches", side_effect=fake) as run:
        result = interpret_semantics(structure, reusable_ai_results=cached)
    assert result["summary"]["ai_cache_reused_count"] == 1
    assert run.call_args.args[0][0]["candidate_id"] == "7_2__m2"
    assert len(run.call_args.args[0]) == 1


def test_teacher_confirmed_semantic_decision_survives_revalidation_without_ai():
    structure = {"job_id": "job", "questions": [{"question_id": "4.2.2", "source_preview": "", "mark_points": [{"count": 1, "code": "CA", "descriptor": "Correct c-value", "notation": "teacher_semantic_confirmed", "semantic": "consistent_accuracy"}]}]}
    with patch("engine.src.memo_engine.semantic._run_batches") as run:
        result = interpret_semantics(structure)
    run.assert_not_called()
    assert result["deterministic_results"][0]["resolution_method"] == "deterministic"
    assert result["exceptions"] == []



def test_revalidation_checks_same_job_semantic_artifact_first():
    structure = {"job_id": "same-job", "questions": [{"question_id": "7.2", "source_preview": "Trigonometry", "mark_points": [{"count": 1, "code": "A", "descriptor": "value", "notation": "shorthand", "semantic": "accuracy"}]}]}
    _, candidates = build_semantic_plan(structure)
    candidate = candidates[0]
    cached = {"phase": "phase4_semantics", "job_id": "same-job", "deterministic_results": [], "ai_results": [{**candidate, "semantic_type": "accuracy", "confidence_score": .99, "band": "green", "rationale": "safe", "resolution_method": "groq:model", "provider_valid": True, "provider_validation_issue": None}], "interpreter_runs": [], "exceptions": [], "summary": {"ai_candidate_count": 1}}

    class FakeDb:
        def __init__(self): self.paths = []
        def find_reusable_semantic_jobs(self, **kwargs): return []
        def download_json(self, bucket, path): self.paths.append(path); return cached

    db = FakeDb()
    exact, source_id, partial, _ = _try_reuse_semantic(db, {"id": "same-job", "user_id": "teacher"}, structure, "hash")
    assert db.paths[0].endswith("/same-job/internal/semantic.json")
    assert source_id == "same-job"
    assert exact is not None
    assert exact["summary"]["interpreter_run_count"] == 0
    assert partial == []



def test_common_given_and_statement_reason_descriptors_normalize_without_ai():
    given = parse_mark_points("1 given")
    combined = parse_mark_points("1 statement/reason")
    assert given[0]["code"] is None and given[0]["descriptor"] == "given"
    assert combined[0]["semantic"] == "statement_reason"
    assert combined[0]["count"] == 1


def test_teacher_language_cannot_introduce_geometry_code_in_non_geometry_context():
    result = {"status": "resolved", "operation": "replace_mark_points", "affected_id": "7.2", "target_id": None, "printed_marks": None, "subtotal": None, "expected_total": 1, "mark_calculation_mode": "additive", "mark_points": [{"count": 1, "code": "R", "descriptor": "rounding"}], "reason": "teacher text", "evidence_basis": ["1R rounding"], "ambiguities": []}
    exception = {"category": "item_total_mismatch", "affected_id": "7.2"}
    context = {"teacher_text": "Question 7.2: 1R rounding", "source_excerpt": "Trigonometry", "current_question": {"question_id": "7.2", "source_preview": "Trigonometry"}, "suggestions": []}
    with pytest.raises(TeacherLanguageError) as error:
        ai_result_to_proposal(result, exception, context, method="test")
    assert error.value.code == "AI_MARK_CODE_OUTSIDE_SUBJECT_PROFILE"
