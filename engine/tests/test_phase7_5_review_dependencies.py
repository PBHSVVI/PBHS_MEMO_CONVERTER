from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REVIEW_PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


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
