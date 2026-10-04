from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REVIEW_PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"
REVIEW_LAB = ROOT / "web" / "phase7-review-lab.html"


def _dependency_source() -> str:
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    match = re.search(
        r"// BEGIN REVIEW DEPENDENCY MODEL\s*(.*?)\s*"
        r"// END REVIEW DEPENDENCY MODEL",
        html,
        flags=re.S,
    )
    assert match, "review dependency model is missing from the review page"
    return match.group(1)


def _source_focus_source() -> str:
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    match = re.search(
        r"// BEGIN SOURCE FOCUS MODEL\s*(.*?)\s*"
        r"// END SOURCE FOCUS MODEL",
        html,
        flags=re.S,
    )
    assert match, "source focus model is missing from the review page"
    return match.group(1)


def _showback_source() -> str:
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    match = re.search(
        r"// BEGIN TEACHER SHOWBACK MODEL\s*(.*?)\s*"
        r"// END TEACHER SHOWBACK MODEL",
        html,
        flags=re.S,
    )
    assert match, "teacher show-back model is missing from the review page"
    return match.group(1)


def _evaluate(exceptions: list[dict], selected_id: str | None = None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the review dependency regression")
    program = (
        _dependency_source()
        + "\nconst list=JSON.parse(process.argv[1]);"
        + "\nconst selected=process.argv[2] ? list.find(x=>x.id===process.argv[2]) : choosePrimary(list);"
        + "\nconsole.log(JSON.stringify({primary:choosePrimary(list),context:selected?reviewDependencyContext(selected,list):null,dependent:list.filter(x=>isDependent(x,list)).map(x=>x.id)}));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(exceptions), selected_id or ""],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _showback(correction: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the review show-back regression")
    program = (
        _showback_source()
        + "\nconsole.log(JSON.stringify(teacherShowBackModel(JSON.parse(process.argv[1]))));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(correction)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _child(identifier: str, affected_id: str) -> dict:
    return {
        "id": identifier,
        "category": "item_total_mismatch",
        "affected_id": affected_id,
        "message": f"Question {affected_id} needs review.",
    }


def _parent(identifier: str, affected_id: str, observed: int, computed: int) -> dict:
    return {
        "id": identifier,
        "category": "question_total_mismatch",
        "affected_id": affected_id,
        "message": (
            f"Question {affected_id} observed subtotal {observed} "
            f"does not equal computed {computed}."
        ),
    }


def test_child_remains_primary_and_parent_context_is_surfaced():
    result = _evaluate([_parent("parent", "11", 16, 17), _child("child", "11.1.1")])
    assert result["primary"]["id"] == "child"
    assert result["dependent"] == ["parent"]
    assert result["context"]["parents"] == [{
        "parent_id": "11",
        "child_id": "11.1.1",
        "source_total": "16",
        "converter_total": "17",
        "message": "Question 11 observed subtotal 16 does not equal computed 17.",
    }]


def test_child_without_parent_has_no_parent_context():
    result = _evaluate([_child("child", "7.4")])
    assert result["primary"]["id"] == "child"
    assert result["context"]["parents"] == []


def test_multiple_child_candidates_do_not_turn_parent_into_duplicate_work():
    exceptions = [
        _parent("parent", "5", 8, 9),
        _child("child-a", "5.1"),
        _child("child-b", "5.2"),
    ]
    result = _evaluate(exceptions)
    assert result["primary"]["id"] == "child-a"
    assert result["dependent"] == ["parent"]
    assert [p["parent_id"] for p in result["context"]["parents"]] == ["5"]


def test_resolved_parent_is_not_retained_after_active_list_refresh():
    before = _evaluate([_parent("parent", "7", 20, 21), _child("child", "7.4")])
    after = _evaluate([])
    assert before["context"]["parents"][0]["parent_id"] == "7"
    assert after["primary"] is None
    assert after["context"] is None


def test_unrelated_question_mismatch_is_not_shown_as_parent_context():
    result = _evaluate([_parent("parent", "5", 8, 9), _child("child", "7.4")], "child")
    assert result["context"]["parents"] == []


def test_teacher_showback_exposes_plain_mark_scheme_lines():
    result = _showback({
        "display_text": "Question 7.4 should use the following 2-mark scheme.",
        "proposed_patch": {
            "operation": "replace_mark_points",
            "affected_id": "7.4",
            "expected_total": 2,
            "mark_points": [
                {"count": 1, "code": "M", "descriptor": "factorising"},
                {"count": 1, "code": "A", "descriptor": "answer"},
            ],
        },
    })
    assert result["summary"].startswith("Question 7.4")
    assert result["mark_points"] == [
        {"count": 1, "code": "M", "descriptor": "factorising"},
        {"count": 1, "code": "A", "descriptor": "answer"},
    ]
    assert result["expected_total"] == 2


def test_teacher_showback_keeps_internal_operation_in_technical_model():
    result = _showback({
        "display_text": "Rename Question 11.12.1 to Question 11.2.1.",
        "proposed_patch": {
            "operation": "rename_question_identifier",
            "target_id": "11.2.1",
        },
    })
    assert result["summary"] == "Rename Question 11.12.1 to Question 11.2.1."
    assert result["operation"] == "rename_question_identifier"
    assert result["target_id"] == "11.2.1"


def test_focused_review_requires_an_explicit_job_id_without_baseline_fallback():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "requestedReviewJob(location.search)" in html
    assert "$('#job').value=jobId" in html
    assert "DEFAULT_JOB_ID" not in html
    assert 'id="job" placeholder=' in html
    assert 'id="job" value=' not in html
    assert "page no longer falls back to the completed acceptance job" in html

def test_review_pages_explain_revalidation_conflicts():
    focused = REVIEW_PAGE.read_text(encoding="utf-8")
    lab = REVIEW_LAB.read_text(encoding="utf-8")
    expected = "Wait for revalidation to finish, then refresh before submitting another correction."
    assert expected in focused
    assert expected in lab
    assert "const canSubmit=['needs_review','correction_pending'].includes(job.status)" in lab
    assert "async function waitForRevalidation()" in lab


def test_review_lab_routes_disposable_job_to_visual_source_review():
    html = REVIEW_LAB.read_text(encoding="utf-8")
    assert 'id="visualReview"' in html
    assert "phase7-5-review/" in html
    assert "?job_id=${encodeURIComponent(jobId)}" in html


def test_strict_major_question_focus_does_not_match_child_or_mark_values():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the review focus regression")
    program = (
        "const textMatches=(text,token)=>String(text).includes(String(token));\n"
        + _source_focus_source()
        + "\nconst blocks=JSON.parse(process.argv[1]);"
        + "\nconsole.log(JSON.stringify(blocks.map(block=>sourceBlockMatches(block,'3',true))));"
    )
    blocks = [
        {"cells": ["6.3.2", "working", "(3)"], "combined": "6.3.2 working (3)"},
        {"cells": ["3", "Question 3 subtotal", "[4]"], "combined": "3 Question 3 subtotal [4]"},
    ]
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(blocks)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == [False, True]


def test_question_8_focus_uses_number_labels_instead_of_subtotals():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the review focus regression")
    program = (
        "const textMatches=(text,token)=>String(text).includes(String(token));\n"
        + _source_focus_source()
        + "\nconst blocks=JSON.parse(process.argv[1]);"
        + "\nconsole.log(JSON.stringify({major:blocks.map(block=>sourceBlockMatches(block,'8',false,true)),child:blocks.map(block=>sourceBlockMatches(block,'8.2',false,true))}));"
    )
    blocks = [
        {"cells": ["", "[8]"], "combined": "[8]"},
        {"cells": ["8.\nworking", "(3)"], "combined": "8. working (3)"},
        {"cells": ["8.2 Determine the coordinates", "(4)"], "combined": "8.2 Determine the coordinates (4)"},
        {"cells": ["Question 10 content", "[5]"], "combined": "Question 10 content [5]"},
    ]
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(blocks)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == {
        "major": [False, True, False, False],
        "child": [False, False, True, False],
    }


def test_question_8_review_labels_the_missing_8_1_decision_point():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "contextAnchors:['8.2']" in html
    assert "targetAnchor:'8'" in html
    assert "targetLabel:'This scored row should be numbered 8.1'" in html


def test_question_8_suggestion_is_confirmation_ready_without_ai():
    source = (ROOT / "supabase" / "functions" / "submit-correction" / "index.ts").read_text(
        encoding="utf-8"
    )
    assert '"scored_major_precedes_subquestions"' in source
    assert 'operation: "rename_question_identifier"' in source


def test_teacher_showback_exposes_complete_content_replacement():
    result = _showback({
        "display_text": "Replace the question or memo content for Question 11.2.1.",
        "proposed_patch": {
            "operation": "replace_item_content",
            "target_id": "11.2.1",
            "question_text": "Show that the number is 2 786 918 400.",
            "solution_lines": ["4 factorial times 24", "= 2 786 918 400"],
            "expected_total": 4,
            "mark_points": [
                {"count": 3, "code": "A", "descriptor": "calculation"},
                {"count": 1, "code": "A", "descriptor": "answer"},
            ],
        },
    })
    assert result["question_text"].startswith("Show that")
    assert result["solution_lines"] == ["4 factorial times 24", "= 2 786 918 400"]
    assert result["expected_total"] == 4


def test_every_review_exposes_content_editor_and_guide():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert 'id="contentTarget"' in html
    assert 'id="contentQuestion"' in html
    assert 'id="contentSolution"' in html
    assert 'id="contentMarking"' in html
    assert 'id="submitContent"' in html
    assert "Help with corrections" in html
    assert "It does not depend on punctuation or AI interpretation" in html


def test_structured_content_submission_is_confirmation_ready():
    source = (ROOT / "supabase" / "functions" / "submit-correction" / "index.ts").read_text(
        encoding="utf-8"
    )
    assert "body.content_correction" in source
    assert 'operation: "replace_item_content"' in source
    assert 'exceptionStatus = "awaiting_confirmation"' in source


def test_saved_failed_interpretation_opens_editor_without_automatic_retry():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    start = html.index("async function retrySavedInterpretation(corr)")
    end = html.index("async function waitProposal", start)
    function_source = html[start:end]
    assert "SAVED INTERPRETATION NEEDS EDITING" in function_source
    assert "showRecovery(corr" in function_source
    assert "retry-correction-reinterpretation" not in function_source


def test_grouped_allocation_review_uses_atomic_structured_editor():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    edge = (ROOT / "supabase" / "functions" / "submit-correction" / "index.ts").read_text(encoding="utf-8")
    assert 'id="allocationEditor"' in html
    assert 'id="submitAllocations"' in html
    assert "Review all corrections" in html
    assert "resolve_question_allocation_pairing" in edge
    assert "invalid_allocation_target_set" in edge
    assert "grouped_allocation_requires_structured_editor" in edge


def test_review_acceptance_uses_source_defined_total():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "source_defined_total" in html
    assert "total_150" not in html
    assert "eleven_questions" not in html
    assert "computed_total)===Number(canonical?.totals?.computed)" in html
