from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


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


def test_confirmation_verification_distinguishes_effective_and_withdrawal_rows():
    model = _section("CONFIRMED STAGING VERIFICATION MODEL")
    program = model + r"""
const x=JSON.parse(process.argv[1]);
console.log(JSON.stringify({
 normal:confirmedEffectiveStagingState(x.normal,[x.normal]),
 missing:confirmedEffectiveStagingState(x.normal,[]),
 restored:confirmedEffectiveStagingState(x.restore,[]),
 predecessorStillEffective:confirmedEffectiveStagingState(x.restore,[x.old]),
 withdrawalUnexpectedlyEffective:confirmedEffectiveStagingState(x.restore,[x.restore]),
}));
"""
    old = {"id": "old", "proposed_patch": {"operation": "replace_item_content", "target_id": "2.1", "expected_total": 1}}
    normal = {"id": "new", "proposed_patch": {"operation": "replace_item_content", "target_id": "3.2", "expected_total": 3}}
    restore = {"id": "restore", "proposed_patch": {"operation": "withdraw_confirmed_correction", "target_id": "2.1", "supersedes_correction_id": "old", "source_restoration": True}}
    result = _node(program, {"old": old, "normal": normal, "restore": restore})
    assert result["normal"]["ok"] is True
    assert result["missing"] == {"ok": False, "restoration": False, "error": "The confirmed correction was not found in the staged ledger."}
    assert result["restored"] == {"ok": True, "restoration": True, "target": "2.1"}
    assert result["predecessorStillEffective"]["ok"] is False
    assert "still effective" in result["predecessorStillEffective"]["error"]
    assert result["withdrawalUnexpectedlyEffective"]["ok"] is False


def test_restoration_and_predecessor_are_excluded_while_q2_children_total_nine():
    dependency = _section("REVIEW DEPENDENCY MODEL")
    program = dependency + r"""
const x=JSON.parse(process.argv[1]);
const effective=effectiveStagedCorrections(x);
console.log(JSON.stringify({ids:effective.map(item=>item.id),total:effective.reduce((sum,item)=>sum+Number(item.proposed_patch.expected_total||0),0)}));
"""
    rows = [
        {"id": "old", "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": "2.1", "expected_total": 1}},
        {"id": "restore", "confirmation_status": "confirmed", "proposed_patch": {"operation": "withdraw_confirmed_correction", "target_id": "2.1", "supersedes_correction_id": "old", "source_restoration": True}},
        *[
            {"id": qid, "confirmation_status": "confirmed", "proposed_patch": {"operation": "replace_item_content", "target_id": qid, "expected_total": marks}}
            for qid, marks in (("2.1.1", 1), ("2.1.2", 1), ("2.2", 2), ("2.3", 2), ("2.4", 3))
        ],
    ]
    result = _node(program, rows)
    assert result == {"ids": ["2.1.1", "2.1.2", "2.2", "2.3", "2.4"], "total": 9}


def test_confirm_current_keeps_durable_guard_and_reports_restoration_success():
    page = PAGE.read_text(encoding="utf-8")
    confirm = page.split("async function confirmCurrent()", 1)[1].split("async function applyStagedBatch", 1)[0]
    assert "r?.correction?.id!==correction.id" in confirm
    assert "r?.correction?.confirmation_status!=='confirmed'" in confirm
    assert "confirmedEffectiveStagingState(correction,currentStaged)" in confirm
    assert "Saved ✓ — Question ${verification.target} restored to the original memo state." in confirm
    assert "currentStaged.some(item=>item.id===correction.id)" not in confirm
    assert "submit-correction" not in confirm
    assert "submitChildRepair" not in confirm


def test_reload_model_does_not_create_a_duplicate_restoration():
    page = PAGE.read_text(encoding="utf-8")
    load = page.split("async function loadReviewState()", 1)[1].split("async function updateBatchPanel", 1)[0]
    assert "stagedCorrections()" in load
    assert "submit-correction" not in load
    assert "confirm-correction" not in load
