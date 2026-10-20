from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


def _model() -> str:
    source = PAGE.read_text(encoding="utf-8")
    match = re.search(
        r"// BEGIN VISUAL EVIDENCE FOCUS MODEL\s*(.*?)\s*// END VISUAL EVIDENCE FOCUS MODEL",
        source,
        re.S,
    )
    assert match
    return match.group(1)


def _node(expression: str, value: object) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    program = (
        "function compareQuestionIds(a,b){return String(a).localeCompare(String(b),undefined,{numeric:true})}\n"
        + _model()
        + f"\nconst v=JSON.parse(process.argv[1]);console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, json.dumps(value)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_parent_q3_collects_complete_family_and_all_pages_without_mutation():
    value = {
        "ex": {"category": "question_total_mismatch", "affected_id": "3"},
        "structure": {
            "questions": [
                {"question_id": "3", "source_page": 2, "source_block_index": 4},
                {"question_id": "3.1", "source_page": 2, "source_block_index": 5},
                {"question_id": "3.2", "source_page": 3, "source_block_index": 6},
                {"question_id": "3.3", "source_page": 3, "source_block_index": 7},
                {"question_id": "30", "source_page": 9, "source_block_index": 20},
            ]
        },
        "normalized": {},
    }
    result = _node(
        "({context:parentQuestionFamilyContext(v.ex,v.structure,v.normalized),after:v})",
        value,
    )
    context = result["context"]
    assert context["current_ids"] == ["3", "3.1", "3.2", "3.3"]
    assert context["pages"] == [2, 3]
    assert context["source_block_indexes"] == [4, 5, 6, 7]
    assert context["label"].startswith("Question 3 family")
    assert "3.3" in context["label"]
    assert result["after"] == value


def test_family_matching_is_segment_aware_for_nested_parents():
    cases = [
        ["3", "3", True],
        ["3.2", "3", True],
        ["30", "3", False],
        ["2.1", "2.1", True],
        ["2.1.4", "2.1", True],
        ["2.10", "2.1", False],
    ]
    assert _node("v.map(x=>sameQuestionOrDescendant(...x))", cases) == [
        True,
        True,
        False,
        True,
        True,
        False,
    ]


def test_leaf_review_does_not_activate_parent_family_mode():
    value = {
        "ex": {"category": "item_total_mismatch", "affected_id": "3.2"},
        "structure": {"questions": [{"question_id": "3.2", "source_page": 3}]},
        "normalized": {},
    }
    assert _node("parentQuestionFamilyContext(v.ex,v.structure,v.normalized)", value) is None
    focused = PAGE.read_text(encoding="utf-8").split(
        "async function renderFocusedEvidence()", 1
    )[1].split("function renderFullMemo", 1)[0]
    assert "if(!family&&await renderVisualEvidenceCrop" in focused


def test_renamed_family_keeps_current_and_source_identity_for_q6():
    value = {
        "ex": {"category": "question_total_mismatch", "affected_id": "6"},
        "structure": {
            "questions": [
                {
                    "question_id": "6.2.1",
                    "source_question_id": "4.2.1",
                    "source_page": 5,
                    "source_block_index": 12,
                },
                {
                    "question_id": "6.2.2",
                    "source_question_id": "4.2.2",
                    "source_page": 6,
                    "source_block_index": 13,
                },
            ]
        },
        "normalized": {},
    }
    context = _node("parentQuestionFamilyContext(v.ex,v.structure,v.normalized)", value)
    assert context["current_ids"] == ["6.2.1", "6.2.2"]
    assert context["source_ids"] == ["4.2.1", "6.2.1", "4.2.2", "6.2.2"]
    assert context["renamed_labels"] == [
        "6.2.1 (source label 4.2.1)",
        "6.2.2 (source label 4.2.2)",
    ]
    assert context["pages"] == [5, 6]
    assert context["source_block_indexes"] == [12, 13]


def test_parent_viewer_has_distinct_discrepancy_and_context_treatment():
    page = PAGE.read_text(encoding="utf-8")
    assert "Current discrepancy: Question ${family.target} subtotal" in page
    assert "familyFocusLabel" in page
    assert "familyMemberContext" in page
    assert "familyContextRow" in page
    assert "renderPdfQuestionFamily" in page
    assert "for(const page of context.pages)" in page
    assert 'id="toggleFull"' in page
    assert "@media(max-width:900px)" in page
    assert "@media(max-width:600px)" in page


def test_review_version_is_4_12_4():
    page = PAGE.read_text(encoding="utf-8")
    assert "Phase 8 Review v4.12.4" in page
    assert "phase8-review-v4.12.4" in page

