from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from engine.src.memo_engine.corrections import apply_confirmed_corrections, effective_correction_history
from engine.src.memo_engine.ingestion import extract_docx_text
from engine.src.memo_engine.normalization import normalize_docx
from engine.src.memo_engine.phase7_5 import apply_phase7_5_patch
from engine.src.memo_engine.structure import parse_mark_points

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs/phase7-5-review/index.html"


@pytest.mark.parametrize(("text", "count"), [("✓ answer", 1), ("✓✓ answer", 2), ("x = 2 ✓ answer", 1), ("x = 2; ✓✓ answer", 2), ("✓ method", 1), ("✓✓✓ answers", 3)])
def test_inline_ticks_preserve_numerical_marks(text, count):
    points = parse_mark_points(text)
    assert len(points) == 1 and points[0]["count"] == count
    assert points[0]["notation"] == "tick"


def test_tick_semantics_and_mixed_shorthand_do_not_lose_or_duplicate_marks():
    assert parse_mark_points("✓ method")[0]["semantic"] == "method"
    ca = parse_mark_points("✓ answer (CA)")[0]
    assert ca["count"] == 1 and ca["code"] == "CA" and ca["semantic"] == "consistent_accuracy"
    unknown = parse_mark_points("work shown ✓")
    assert unknown[0]["count"] == 1 and unknown[0]["semantic"] == "other"
    assert sum(item["count"] for item in parse_mark_points("1A answer ✓")) == 1


def _docx(symbol_font: str, symbol_char: str) -> bytes:
    xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>x = 2 </w:t><w:sym w:font="{symbol_font}" w:char="{symbol_char}"/><w:t> answer</w:t></w:r></w:p></w:body></w:document>'''
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return out.getvalue()


def test_verified_ooxml_tick_survives_ingestion_and_normalization():
    data = _docx("Wingdings 2", "F050")
    assert "x = 2 ✓ answer" in extract_docx_text(data)["text"]
    normalized = normalize_docx(data)
    paragraph = normalized["units"][0]
    assert "✓" in paragraph["text"]
    symbol = next(item for item in paragraph["segments"] if item["type"] == "symbol")
    assert symbol == {"type": "symbol", "text": "✓", "font": "Wingdings 2", "char": "F050", "canonical": "✓", "unresolved": False}


def test_unknown_ooxml_symbol_is_preserved_as_unresolved_evidence():
    data = _docx("Wingdings", "F0AA")
    extracted = extract_docx_text(data)
    assert "SYM font=Wingdings char=F0AA" in extracted["text"]
    assert extracted["symbols"][0]["unresolved"] is True
    symbol = next(item for item in normalize_docx(data)["units"][0]["segments"] if item["type"] == "symbol")
    assert symbol["font"] == "Wingdings" and symbol["char"] == "F0AA" and symbol["unresolved"] is True


def _insertion(cid, day, qid, supersedes=None):
    patch = {"operation": "insert_missing_child_question", "category": "question_total_mismatch", "affected_id": "6", "parent_id": "6", "target_id": qid, "question_id": qid, "printed_marks": 6, "expected_total": 6, "mark_points": [{"count": 1, "code": "A", "descriptor": f"feature {i}", "source": f"1A feature {i}"} for i in range(6)]}
    if supersedes:
        patch.update({"supersedes_correction_id": supersedes, "supersession_reason": "teacher_amended_previous_change"})
    return {"id": cid, "confirmation_status": "confirmed", "confirmed_at": f"2026-10-{day:02d}T10:00:00Z", "proposed_patch": patch}


def test_amendment_explicitly_supersedes_across_target_rename_and_keeps_history():
    old = _insertion("old", 1, "6.1.1")
    new = _insertion("new", 2, "6.1", "old")
    effective, history = effective_correction_history([old, new])
    assert [item["id"] for item in effective] == ["new"]
    by_id = {item["correction_id"]: item for item in history}
    assert by_id["old"]["effective"] is False
    assert by_id["old"]["superseded_by"] == "new"
    assert by_id["old"]["supersession_reason"] == "teacher_amended_previous_change"


def test_withdrawal_supersedes_prior_without_deleting_history_or_replay():
    old = _insertion("old", 1, "6.1.1")
    withdrawal = {"id": "withdraw", "confirmation_status": "confirmed", "confirmed_at": "2026-10-02T10:00:00Z", "proposed_patch": {"operation": "withdraw_confirmed_correction", "category": "correction_target_invalid", "affected_id": "6.1.1", "supersedes_correction_id": "old"}}
    effective, history = effective_correction_history([old, withdrawal])
    assert [item["id"] for item in effective] == ["withdraw"]
    assert history[0]["supersession_reason"] == "teacher_withdrew_previous_change"
    result, applied, issues = apply_confirmed_corrections({"questions": [], "exceptions": [], "summary": {}}, {}, [old, withdrawal])
    assert issues == [] and applied[0]["withdrawn"] is True
    assert result["questions"] == []


def test_missing_child_replay_does_not_require_transient_parent_exception_and_balances_q6():
    structure = {"questions": [{"question_id": q, "path": [6, int(q[-1])], "depth": 2, "printed_marks": n, "computed_shorthand_marks": n, "mark_points": []} for q, n in [("6.2", 8), ("6.3", 4), ("6.4", 2)]], "exceptions": []}
    correction = _insertion("new", 2, "6.1")
    result, applied, issues = apply_confirmed_corrections(structure, {}, [correction])
    assert issues == [] and applied[0]["target_id"] == "6.1"
    assert sum(int(q.get("computed_shorthand_marks") or 0) for q in result["questions"]) == 20


def test_invalid_parent_scope_and_duplicate_are_rejected_atomically():
    structure = {"questions": [{"question_id": "6.1", "path": [6, 1], "depth": 2}], "exceptions": []}
    original = json.loads(json.dumps(structure))
    patch = _insertion("x", 1, "6.1")["proposed_patch"]
    applied, issue, handled = apply_phase7_5_patch(structure, {}, correction_id="x", category="question_total_mismatch", affected_id="6", operation="insert_missing_child_question", patch=patch)
    assert handled and applied is None and issue["category"] == "correction_target_conflict" and structure == original
    bad = dict(patch, parent_id="7", affected_id="7", question_id="6.2", target_id="6.2")
    applied, issue, handled = apply_phase7_5_patch(structure, {}, correction_id="y", category="question_total_mismatch", affected_id="7", operation="insert_missing_child_question", patch=bad)
    assert handled and applied is None and issue["category"] == "correction_target_invalid" and structure == original


def test_v410_recovery_and_progressive_disclosure_contract():
    html = PAGE.read_text(encoding="utf-8")
    submit = (ROOT / "supabase/functions/submit-correction/index.ts").read_text(encoding="utf-8")
    assert "Previous change could not be applied" in html
    assert "Edit previous change" in html and "Withdraw this change" in html
    assert "supersedes_correction_id" in html
    assert 'prior.confirmation_status !== "confirmed"' in submit and "prior.applied_at" in submit
    assert 'action === "amend"' in submit and 'action === "withdraw"' in submit
    assert 'operation: "withdraw_confirmed_correction"' in submit
    assert '<details><summary>Technical details</summary>' in html
    assert 'id="reviewLogin"' in html and "addEventListener('submit',startReview)" in html
    assert 'id="correctionTool"' in html and "setCorrectionTool" in html
    assert "$('#correctionTool').onchange" in html
    assert "selected!=='typed'" in html and "selected!=='content'" in html and "selected!=='file'" in html
    assert "Taking a little longer than usual — still working" in html
    assert "Estimated remaining:" in html and "Estimating…" in html
    assert "setInterval(()=>currentJobData&&updateProcessingPanel(currentJobData),1000)" in html
    assert "['failed','failed_retryable'].includes(j.status)" in html
    assert "monitorProcessing()" in html and "getSession" in html
    assert "if(!normal.length)" in html
    assert "semantic.json" not in html  # frontend does not disturb engine cache artifacts
