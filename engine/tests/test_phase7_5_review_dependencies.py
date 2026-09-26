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
