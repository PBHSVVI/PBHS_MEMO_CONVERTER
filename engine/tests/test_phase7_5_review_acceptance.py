from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REVIEW_PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


def _evaluator_source() -> str:
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    match = re.search(
        r"// BEGIN CORRECTION AUDIT EVALUATOR\s*(.*?)\s*"
        r"// END CORRECTION AUDIT EVALUATOR",
        html,
        flags=re.S,
    )
    assert match, "correction audit evaluator is missing from the review page"
    return match.group(1)


def _evaluate(canonical: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the review acceptance regression")
    program = (
        _evaluator_source()
        + "\nconst canonical=JSON.parse(process.argv[1]);"
        + "\nconsole.log(JSON.stringify(evaluateCorrectionAudit(canonical)));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(canonical)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _canonical(*, effective_applied=True, issue_count=0, bad_successor=False):
    history = [
        {
            "correction_id": "old",
            "operation": "set_item_total_override",
            "affected_id": "11.1.1",
            "domain": "item_total",
            "effective": False,
            "superseded_by": "missing" if bad_successor else "new",
            "supersession_reason": "newer_confirmed_marking_decision",
            "applied": False,
        },
        {
            "correction_id": "new",
            "operation": "replace_mark_points",
            "affected_id": "11.1.1",
            "domain": "mark_scheme",
            "effective": True,
            "superseded_by": None,
            "supersession_reason": None,
            "applied": effective_applied,
        },
    ]
    return {"audit": {"correction_overlay": {
        "confirmed_count": 2,
        "effective_count": 1,
        "superseded_count": 1,
        "applied_count": 1 if effective_applied else 0,
        "issue_count": issue_count,
        "history": history,
    }}}


def test_effective_history_accepts_superseded_unapplied_correction():
    result = _evaluate(_canonical())
    assert all(result["checks"].values())
    assert result["counts"] == {
        "confirmed": 2,
        "effective": 1,
        "superseded": 1,
        "applied_effective": 1,
        "issues": 0,
    }
    assert result["failures"] == []


@pytest.mark.parametrize(
    ("canonical", "failed_check", "message"),
    [
        ({"audit": {}}, "correction_audit_present", "audit is missing"),
        (_canonical(effective_applied=False), "effective_corrections_applied", "was not applied"),
        (_canonical(issue_count=1), "correction_application_issues_zero", "issues remain"),
        (_canonical(bad_successor=True), "superseded_corrections_valid", "superseded_by"),
    ],
)
def test_correction_history_failures_are_explicit(canonical, failed_check, message):
    result = _evaluate(canonical)
    assert result["checks"][failed_check] is False
    assert any(message in failure for failure in result["failures"])


def test_historical_applied_at_is_diagnostic_only():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "all_confirmed_applied" not in html
    assert "every(c=>!!c.applied_at)" not in html
    assert "historical_rows_without_applied_at" in html


def test_applied_count_must_equal_effective_count():
    canonical = _canonical()
    canonical["audit"]["correction_overlay"]["applied_count"] = 0
    result = _evaluate(canonical)
    assert result["checks"]["correction_applied_count_matches_effective"] is False


def test_superseded_entry_cannot_be_currently_applied():
    canonical = _canonical()
    canonical["audit"]["correction_overlay"]["history"][0]["applied"] = True
    result = _evaluate(canonical)
    assert result["checks"]["superseded_corrections_valid"] is False
