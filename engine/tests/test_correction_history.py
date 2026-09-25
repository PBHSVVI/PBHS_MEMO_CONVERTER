from __future__ import annotations

import copy

import pytest

from engine.src.memo_engine.corrections import (
    apply_confirmed_corrections,
    attach_correction_audit,
    effective_correction_history,
)
from engine.src.memo_engine.phase7_5 import phase7_5_deterministic_proposal
from engine.src.memo_engine.canonical import _marking_points_for_alternatives


def correction(cid, day, patch, status="confirmed"):
    return {
        "id": cid, "confirmation_status": status,
        "confirmed_at": f"2026-09-{day:02d}T12:00:00Z",
        "proposed_patch": patch, "display_text": "Original teacher evidence",
    }


def scheme(cid="new", day=22, target="11.1.1"):
    patch, _, _ = phase7_5_deterministic_proposal(
        {"category": "correction_mark_total_invalid", "affected_id": target},
        "2A for 3 correct answers; 1A for 2 correct answers",
    )
    return correction(cid, day, patch)


def override(cid="old", day=21, target="11.1.1", total=3):
    return correction(cid, day, {
        "operation": "set_item_total_override", "category": "item_total_mismatch",
        "affected_id": target, "printed_marks": total,
    })


def structure(*targets):
    return {
        "questions": [{
            "question_id": target, "path": list(map(int, target.split("."))),
            "source_block_index": index, "printed_marks": 2,
            "computed_shorthand_marks": 3, "mark_points": [],
        } for index, target in enumerate(targets or ("11.1.1",))],
        "exceptions": [], "summary": {},
    }


def test_obsolete_three_mark_override_is_auditable_but_never_replayed():
    original = structure()
    old = override(cid="473f7290-4ce4-4d8c-a269-20705d92de7a")
    old["applied_at"] = "2026-09-21T13:00:00Z"
    # Deliberately shuffled: confirmation chronology, not input order, controls replay.
    corrections = [scheme(), old]
    saved = copy.deepcopy(corrections)
    result, applied, issues = apply_confirmed_corrections(original, {}, corrections)
    assert issues == []
    assert [item["correction_id"] for item in applied] == ["new"]
    assert result["questions"][0]["printed_marks"] == 2
    assert result["questions"][0]["computed_shorthand_marks"] == 2
    assert result["questions"][0]["mark_calculation_mode"] == "conditional_accuracy"
    canonical_issues = []
    marking = _marking_points_for_alternatives(
        "11.1.1", result["questions"][0], "",
        [[{"block_id": "answer", "type": "math", "semantic_role": "answer"}]],
        {}, canonical_issues,
    )
    assert canonical_issues == []
    assert sum(p["count"] for p in marking[0]) == 2
    assert "PARTIAL_CREDIT_RULE" in marking[0][0]["warnings"]
    assert "2 correct answers" in marking[0][0]["descriptor"]
    assert result["exceptions"] == []
    overlay = result["correction_overlay"]
    assert (overlay["confirmed_count"], overlay["effective_count"],
            overlay["superseded_count"], overlay["applied_count"],
            overlay["issue_count"]) == (2, 1, 1, 1, 0)
    assert overlay["history"][0]["superseded_by"] == "new"
    canonical = {"audit": {"decisions": []}}
    attach_correction_audit(canonical, corrections, overlay)
    historical = next(c for c in canonical["corrections"] if c["correction_id"] == old["id"])
    assert historical["confirmation"]["status"] == "confirmed"
    assert historical["proposed_patch"]["printed_marks"] == 3
    assert historical["historical_applied_at"] == old["applied_at"]
    assert historical["effective"] is False
    assert historical["applied"] is False
    assert historical["superseded_by"] == "new"
    assert canonical["audit"]["correction_overlay"] == overlay
    assert corrections == saved
    assert original == structure()
    assert apply_confirmed_corrections(original, {}, corrections) == (result, applied, issues)


def test_newest_complete_mark_scheme_replaces_older_scheme():
    old = scheme("old", 21)
    old["proposed_patch"]["expected_total"] = 3
    result, applied, issues = apply_confirmed_corrections(structure(), {}, [old, scheme()])
    assert issues == []
    assert [item["correction_id"] for item in applied] == ["new"]
    assert result["correction_overlay"]["history"][0]["superseded_by"] == "new"


def test_numbering_and_marking_on_same_question_both_apply():
    rename = correction("rename", 23, {
        "operation": "rename_question_identifier", "category": "numbering_jump",
        "affected_id": "11.1.1", "target_id": "11.1.2",
    })
    result, applied, issues = apply_confirmed_corrections(structure(), {}, [scheme(), rename])
    assert issues == []
    assert {item["correction_id"] for item in applied} == {"new", "rename"}
    assert result["questions"][0]["question_id"] == "11.1.2"
    assert result["questions"][0]["computed_shorthand_marks"] == 2
    assert result["correction_overlay"]["superseded_count"] == 0


def test_other_question_correction_remains_effective():
    result, applied, issues = apply_confirmed_corrections(
        structure("11.1.1", "7.4"), {},
        [override(), scheme("elsewhere", 20, "7.4"), scheme()],
    )
    assert issues == []
    assert {item["correction_id"] for item in applied} == {"new", "elsewhere"}
    assert all(q["computed_shorthand_marks"] == 2 for q in result["questions"])


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_unconfirmed_replacement_cannot_supersede(status):
    newer = scheme()
    newer["confirmation_status"] = status
    effective, history = effective_correction_history([override(), newer])
    assert [c["id"] for c in effective] == ["old"]
    assert len(history) == 1
    assert history[0]["superseded_by"] is None


def test_invalid_effective_replacement_still_blocks():
    newer = scheme()
    newer["proposed_patch"]["mark_points"] = []
    result, applied, issues = apply_confirmed_corrections(structure(), {}, [override(), newer])
    assert applied == []
    assert [i["category"] for i in issues] == ["correction_mark_scheme_invalid"]
    assert result["summary"]["review_required"] is True
    assert result["correction_overlay"]["effective_count"] == 1


def test_later_total_override_composes_with_scheme_but_replaces_prior_override():
    result, applied, issues = apply_confirmed_corrections(structure(), {}, [
        override(), scheme(), override("latest-total", 23, total=2),
    ])
    assert issues == []
    assert [a["correction_id"] for a in applied] == ["new", "latest-total"]
    assert result["questions"][0]["computed_shorthand_marks"] == 2


@pytest.mark.parametrize("operation,category", [
    ("set_printed_marks", "multiple_printed_allocations"),
    ("set_question_subtotal", "subtotal_sum_unexpected"),
    ("rename_question_identifier", "numbering_jump"),
    ("replace_mark_points", "unsupported_category"),
])
def test_independent_or_unsupported_operations_are_not_suppressed(operation, category):
    independent = correction("independent", 20, {
        "operation": operation, "category": category, "affected_id": "11.1.1",
    })
    effective, history = effective_correction_history([independent, scheme()])
    assert [c["id"] for c in effective] == ["independent", "new"]
    assert all(h["superseded_by"] is None for h in history)


def test_equal_confirmation_times_have_stable_id_tiebreak():
    first, second = scheme("a", 22), scheme("b", 22)
    assert effective_correction_history([first, second]) == effective_correction_history([second, first])
    effective, _ = effective_correction_history([second, first])
    assert [c["id"] for c in effective] == ["b"]


def test_confirmation_offsets_are_compared_as_instants():
    old, newer = override(), scheme()
    old["confirmed_at"] = "2026-09-22T14:00:00+02:00"
    newer["confirmed_at"] = "2026-09-22T12:01:00Z"
    effective, _ = effective_correction_history([newer, old])
    assert [c["id"] for c in effective] == ["new"]


def test_legacy_history_without_timestamps_preserves_supplied_order():
    old, newer = override(), scheme()
    del old["confirmed_at"]
    del newer["confirmed_at"]
    effective, history = effective_correction_history([old, newer])
    assert [c["id"] for c in effective] == ["new"]
    assert history[0]["superseded_by"] == "new"


def test_latest_total_only_override_replaces_old_total_only_override():
    effective, history = effective_correction_history([
        override(), override("new-total", 22, total=2),
    ])
    assert [c["id"] for c in effective] == ["new-total"]
    assert history[0]["superseded_by"] == "new-total"
