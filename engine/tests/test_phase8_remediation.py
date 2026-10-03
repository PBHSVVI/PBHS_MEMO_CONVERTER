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


def test_long_processing_has_no_fixed_timeout_and_remains_resumable():
    html = PAGE.read_text(encoding="utf-8")
    assert "for(let i=0;i<300" not in html
    assert "Timed out waiting for Phase 7.5 revalidation" not in html
    assert "Still processing — you can leave this page and return later." in html
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
    assert "Source subtotal is wrong" in html
    assert "Source subtotal is correct — inspect/correct a child" in html
    assert "deterministic_parent_ledger" in edge
    assert "invalid_parent_reconciliation" in edge


def test_question_workspace_and_staged_batch_preserve_individual_corrections():
    html = PAGE.read_text(encoding="utf-8")
    edge = (ROOT / "supabase" / "functions" / "confirm-correction" / "index.ts").read_text(encoding="utf-8")
    assert 'id="questionWorkspace"' in html
    assert "Projected after staged corrections" in html
    assert "Each confirmed child correction keeps its own audit identity" in html
    assert "Review this item" in html
    assert 'id="applyBatch"' in html
    assert "defer_revalidation:!applyNow" in html
    assert "phase8_correction_staged" in edge
    assert "conflicting_staged_correction" in edge


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
