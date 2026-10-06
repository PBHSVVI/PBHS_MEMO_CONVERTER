from __future__ import annotations

import copy

import pytest

from engine.src.memo_engine.geometry_validation import geometry_consistency_issues
from engine.src.memo_engine.phase7_5 import apply_phase7_5_patch


def _memo(*parts: str) -> dict:
    blocks = [
        {
            "block_id": f"b_{index}",
            "type": "prose",
            "text": part,
            "source_refs": [],
        }
        for index, part in enumerate(parts, 1)
    ]
    return {
        "questions": [{
            "number": "3",
            "items": [{
                "number": "3.2",
                "children": [],
                "alternatives": [{"blocks": blocks}],
            }],
        }],
    }


@pytest.mark.parametrize("line", ["BC perpendicular BC", "AB ⊥ AB"])
def test_self_perpendicular_relationship_requires_review(line: str):
    issues = geometry_consistency_issues(_memo(line))
    assert len(issues) == 1
    assert issues[0]["category"] == "geometry_line_relationship_conflict"
    assert issues[0]["affected_id"] == "3.2"


@pytest.mark.parametrize(
    "conclusion",
    ["BC perpendicular AB", "AB perpendicular BC"],
)
def test_gradient_pair_accepts_either_perpendicular_order(conclusion: str):
    assert geometry_consistency_issues(
        _memo("mBC × mAB = -1", conclusion)
    ) == []


def test_gradient_pair_rejects_wrong_self_pair_with_teacher_message():
    issues = geometry_consistency_issues(
        _memo("mBC × mAB = -1", "therefore BC perpendicular BC")
    )
    assert issues == [{
        "level": "amber",
        "category": "geometry_line_relationship_conflict",
        "affected_id": "3.2",
        "message": (
            "Earlier working compares BC and AB, but the conclusion says BC is "
            "perpendicular to BC. Confirm or edit the named lines."
        ),
    }]


def test_parallel_self_pair_requires_distinct_nearby_evidence():
    assert geometry_consistency_issues(_memo("AB is parallel to AB")) == []
    issues = geometry_consistency_issues(
        _memo("mAB × mCD = -1", "therefore AB parallel to AB")
    )
    assert len(issues) == 1


def test_unrelated_repeated_line_names_do_not_trigger():
    assert geometry_consistency_issues(
        _memo("The point on AB is labelled AB in the explanatory note.")
    ) == []


def test_generic_line_identifiers_are_not_benchmark_specific():
    assert geometry_consistency_issues(
        _memo("mPQ × mRS = -1", "therefore PQ perpendicular RS")
    ) == []
    issues = geometry_consistency_issues(
        _memo("mPQ × mRS = -1", "therefore PQ perpendicular PQ")
    )
    assert len(issues) == 1
    assert "PQ and RS" in issues[0]["message"]


def test_validator_does_not_rewrite_content():
    memo = _memo("mBC × mAB = -1", "BC perpendicular BC")
    original = copy.deepcopy(memo)
    geometry_consistency_issues(memo)
    assert memo == original


def test_existing_content_correction_path_resolves_geometry_exception():
    structure = {
        "questions": [{
            "question_id": "3.2",
            "path": [3, 2],
            "depth": 2,
            "source_block_index": 4,
            "printed_marks": 3,
            "computed_shorthand_marks": 3,
            "mark_points": [],
        }],
        "exceptions": [{
            "category": "geometry_line_relationship_conflict",
            "affected_id": "3.2",
        }],
    }
    patch = {
        "operation": "replace_item_content",
        "category": "geometry_line_relationship_conflict",
        "affected_id": "3.2",
        "target_id": "3.2",
        "question_text": None,
        "solution_lines": ["mBC × mAB = -1", "BC perpendicular AB"],
    }
    applied, issue, handled = apply_phase7_5_patch(
        structure,
        {},
        correction_id="teacher-correction",
        category="geometry_line_relationship_conflict",
        affected_id="3.2",
        operation="replace_item_content",
        patch=patch,
    )
    assert handled is True
    assert issue is None
    assert applied["operation"] == "replace_item_content"
    assert structure["exceptions"] == []
    assert structure["questions"][0]["content_override"]["solution_lines"][-1] == "BC perpendicular AB"
