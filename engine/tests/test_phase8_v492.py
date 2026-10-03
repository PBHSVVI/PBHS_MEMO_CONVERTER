from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.src.memo_engine.phase7_5 import apply_phase7_5_patch

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


def _child_ledger(value: object) -> object:
    helpers = r'''
function majorQuestionId(value){const match=String(value||'').match(/^\d+/);return match?match[0]:''}
function compareQuestionIds(a,b){const aa=String(a).split('.').map(Number),bb=String(b).split('.').map(Number),n=Math.max(aa.length,bb.length);for(let i=0;i<n;i++){const d=(aa[i]??-1)-(bb[i]??-1);if(d)return d}return 0}
function isDependent(){return false}
function parentDiscrepancyDetails(parent){const values=String(parent.message||'').match(/\d+/g)||[];return {source_total:values.at(-2)||null,converter_total:values.at(-1)||null}}
'''
    program = helpers + _section("CHILD REPAIR MODEL") + "\nconst x=JSON.parse(process.argv[1]);console.log(JSON.stringify(questionLedgerModel(x.structure,x.exceptions,x.staged,x.major)));"
    return _node(program, value)


def _q6_value() -> dict:
    return {
        "major": "6",
        "structure": {"questions": [
            {"question_id": "6.2", "printed_marks": 8, "computed_shorthand_marks": 8, "mark_points": [{"count": 8, "source": "8M identity"}]},
            {"question_id": "6.3", "printed_marks": 4, "computed_shorthand_marks": 4, "mark_points": [{"count": 4, "source": "4A intervals"}]},
            {"question_id": "6.4", "printed_marks": 2, "computed_shorthand_marks": 2, "mark_points": [{"count": 2, "source": "2A answers"}]},
        ]},
        "exceptions": [{"id": "parent", "category": "question_total_mismatch", "affected_id": "6", "message": "source subtotal 20; computed total 14"}],
        "staged": [],
    }


def test_q6_exposes_missing_opportunity_without_automatic_insertion():
    result = _child_ledger(_q6_value())
    assert [row["question_id"] for row in result["rows"]] == ["6.2", "6.3", "6.4"]
    assert result["missing_opportunity"] is True
    assert result["computed_total"] == result["projected_total"] == 14


def test_staged_q6_insertion_projects_twenty_and_materializes_row():
    value = _q6_value()
    value["staged"] = [{"proposed_patch": {
        "operation": "insert_missing_child_question", "parent_id": "6", "question_id": "6.1",
        "target_id": "6.1", "printed_marks": 6, "expected_total": 6,
        "mark_points": [{"count": 1, "source": "1A feature"}] * 6,
    }}]
    result = _child_ledger(value)
    assert [row["projected_id"] for row in result["rows"]] == ["6.1", "6.2", "6.3", "6.4"]
    assert result["projected_total"] == 20
    assert result["missing_opportunity"] is False


def test_all_existing_rows_are_editable_and_prefilled():
    html = PAGE.read_text(encoding="utf-8")
    assert "Edit item" in html
    assert "row.printed??(row.computed>0?row.computed:'')" in html
    assert "markingSchemeText(points)" in html
    assert "Possible missing or misnumbered subquestion" in html
    assert "Nothing is inserted automatically" in html


def test_missing_child_insert_is_atomic_and_auditable():
    structure = {
        "questions": [{"question_id": qid, "path": [6, int(qid[-1])], "depth": 2, "source_block_index": index, "printed_marks": marks, "computed_shorthand_marks": marks, "mark_points": [{"count": marks, "descriptor": qid}]} for qid, marks, index in [("6.2", 8, 5), ("6.3", 4, 7), ("6.4", 2, 8)]],
        "exceptions": [{"category": "question_total_mismatch", "affected_id": "6"}],
    }
    labels = ["maximum value 2", "shape of f", "x-intercepts of f", "asymptotes of g", "shape of g", "x-intercepts of g"]
    patch = {"operation": "insert_missing_child_question", "category": "question_total_mismatch", "affected_id": "6", "parent_id": "6", "target_id": "6.1", "question_id": "6.1", "printed_marks": 6, "expected_total": 6, "mark_points": [{"count": 1, "code": "A", "descriptor": label, "source": f"1A {label}"} for label in labels], "reconciliation_scope": "missing_child"}
    applied, issue, handled = apply_phase7_5_patch(structure, {}, correction_id="corr", category="question_total_mismatch", affected_id="6", operation="insert_missing_child_question", patch=patch)
    assert handled and issue is None
    inserted = next(question for question in structure["questions"] if question["question_id"] == "6.1")
    assert inserted["computed_shorthand_marks"] == inserted["printed_marks"] == 6
    assert inserted["correction_overlay"]["operation"] == "insert_missing_child_question"
    assert applied["target_id"] == "6.1"
    assert structure["exceptions"] == []


def test_duplicate_child_rejected_without_partial_mutation():
    structure = {"questions": [{"question_id": "6.1", "path": [6, 1], "depth": 2, "printed_marks": 6, "computed_shorthand_marks": 6, "mark_points": []}], "exceptions": [{"category": "question_total_mismatch", "affected_id": "6"}]}
    original = copy.deepcopy(structure)
    patch = {"operation": "insert_missing_child_question", "parent_id": "6", "question_id": "6.1", "target_id": "6.1", "printed_marks": 1, "expected_total": 1, "mark_points": [{"count": 1, "code": "A", "descriptor": "answer"}]}
    applied, issue, handled = apply_phase7_5_patch(structure, {}, correction_id="corr", category="question_total_mismatch", affected_id="6", operation="insert_missing_child_question", patch=patch)
    assert handled and applied is None and issue["category"] == "correction_target_conflict"
    assert structure == original


def test_missing_child_is_confirmation_gated_and_staged_conflicts_are_bounded():
    html = PAGE.read_text(encoding="utf-8")
    submit = (ROOT / "supabase/functions/submit-correction/index.ts").read_text(encoding="utf-8")
    confirm = (ROOT / "supabase/functions/confirm-correction/index.ts").read_text(encoding="utf-8")
    assert "Review this addition" in html and "SHOW-BACK — not applied yet" in html
    assert 'operation: "insert_missing_child_question"' in submit
    assert 'exceptionStatus = "awaiting_confirmation"' in submit
    assert 'missing_child_identifier_conflict' in submit
    assert 'stagedTarget(correction.proposed_patch)' in confirm
    assert 'conflicting_staged_correction' in confirm
    assert 'patch.reconciliation_scope === "missing_child"' in confirm


def test_q6_source_region_excludes_q5_and_includes_twenty_subtotal():
    blocks = [
        {"combined": "5.4 prior work", "cells": ["5.4 prior work"]}, {"combined": "[13]", "cells": ["[13]"]},
        {"combined": "graph features worth 6", "cells": ["graph features worth 6"]}, {"combined": "6.2 identity", "cells": ["6.2 identity"]},
        {"combined": "6.3 intervals", "cells": ["6.3 intervals"]}, {"combined": "6.4 answers", "cells": ["6.4 answers"]},
        {"combined": "[20]", "cells": ["[20]"]}, {"combined": "7.1 next question", "cells": ["7.1 next question"]},
    ]
    structure = {"questions": [{"question_id": "6.2", "source_block_index": 3}, {"question_id": "6.3", "source_block_index": 4}, {"question_id": "6.4", "source_block_index": 5}]}
    helpers = "function majorQuestionId(v){return String(v).split('.')[0]}\nfunction textMatches(a,b){return String(a).includes(String(b))}\n"
    result = _node(helpers + _section("SOURCE FOCUS MODEL") + "\nconst x=JSON.parse(process.argv[1]);console.log(JSON.stringify(questionRegionBounds(x.blocks,x.structure,'6')));", {"blocks": blocks, "structure": structure})
    assert result["start"] == 2 and result["end"] == 6
    assert "exact child alignment requires review" in result["label"]
