#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

EXPECTED_BLOB_SHAS = {
    "engine/src/memo_engine/phase7_5.py": "119b13b5c4715cb9aa9f1370f20f695d88253d97",
    "engine/tests/test_phase7_5_raw_categories.py": "aea1f2c4e1365756d4c1bace1d1d40c21478b172",
    "docs/phase7-5-review/index.html": "f88ef39d79fdd7702de1420b8a36215314b3ee19",
}


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_phase(text: str) -> str:
    text = replace_once(
        text,
        'MARK_TOTAL_RE = re.compile(r"(?i)\\b(\\d{1,2})\\s*marks?\\b")\nSUBTOTAL_INSTRUCTION_RE = re.compile(',
        'MARK_TOTAL_RE = re.compile(r"(?i)\\b(\\d{1,2})\\s*marks?\\b")\n'
        'TEACHER_ITEM_TOTAL_RE = re.compile(\n'
        '    r"(?i)^\\s*(?:(?:award|use|make(?:\\s+it)?|total(?:\\s+is)?|"\n'
        '    r"set(?:\\s+(?:the\\s+)?(?:item\\s+)?total(?:\\s+to)?)?)\\s+)?"\n'
        '    r"(\\d{1,2})\\s*marks?\\s*[.!]?\\s*$"\n'
        ')\n'
        'BARE_ITEM_TOTAL_RE = re.compile(r"^\\s*\\(\\s*(\\d{1,2})\\s*\\)\\s*$")\n'
        'SUBTOTAL_INSTRUCTION_RE = re.compile(',
        "item-total regexes",
    )

    apply_fn = r'''
def _apply_set_item_total_override(
    structure: dict[str, Any],
    *,
    correction_id: str,
    category: str,
    affected_id: str,
    patch: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    question = _question(structure, affected_id)
    if question is None:
        return None, _issue(
            "correction_evidence_unresolved",
            affected_id,
            f"Confirmed correction {correction_id} could not resolve Question {affected_id}.",
        )

    try:
        chosen = int(patch.get("printed_marks"))
    except Exception:
        chosen = 0
    if not 1 <= chosen <= 20:
        return None, _issue(
            "correction_mark_total_invalid",
            affected_id,
            f"Confirmed correction {correction_id} does not contain a safe item total.",
        )

    computed = int(question.get("computed_shorthand_marks") or 0)
    if computed <= 0:
        return None, _issue(
            "correction_evidence_unresolved",
            affected_id,
            f"Question {affected_id} has no bounded computed mark total to reconcile.",
        )
    if chosen != computed:
        return None, _issue(
            "correction_mark_total_invalid",
            affected_id,
            (
                f"Teacher total {chosen} does not match the existing computed mark "
                f"scheme total {computed} for Question {affected_id}; provide the "
                "replacement mark scheme instead."
            ),
        )

    original = question.get("printed_marks")
    question["printed_marks"] = chosen
    question["correction_overlay"] = {
        "correction_id": correction_id,
        "operation": "set_item_total_override",
        "source_printed_marks": original,
    }
    _remove_exception(structure, category, affected_id)
    _remove_exception(structure, "mark_arithmetic_mismatch", affected_id)

    return {
        "correction_id": correction_id,
        "operation": "set_item_total_override",
        "category": category,
        "affected_id": affected_id,
        "target_id": affected_id,
        "source_printed_marks": original,
        "printed_marks": chosen,
        "mark_total": computed,
        "source_block_index": question.get("source_block_index"),
    }, None

'''
    text = replace_once(
        text,
        "\ndef _apply_replace_mark_points(\n",
        "\n" + apply_fn + "def _apply_replace_mark_points(\n",
        "item-total apply function",
    )

    dispatcher_old = '''    if (
        category in {"mark_arithmetic_mismatch", "item_total_mismatch"}
        and operation == "replace_mark_points"
    ):
'''
    dispatcher_new = '''    if category == "item_total_mismatch" and operation == "set_item_total_override":
        applied, issue = _apply_set_item_total_override(
            structure,
            correction_id=correction_id,
            category=category,
            affected_id=affected,
            patch=patch,
        )
        return applied, issue, True

    if (
        category in {"mark_arithmetic_mismatch", "item_total_mismatch"}
        and operation == "replace_mark_points"
    ):
'''
    text = replace_once(text, dispatcher_old, dispatcher_new, "item-total dispatcher")

    start = text.index('    if category in {"mark_arithmetic_mismatch", "item_total_mismatch"}:\n')
    end = text.index('    if category == "subtotal_sum_unexpected":\n', start)

    new_block = '''    if category in {"mark_arithmetic_mismatch", "item_total_mismatch"}:
        if category == "item_total_mismatch":
            total_match = TEACHER_ITEM_TOTAL_RE.fullmatch(evidence_text.strip())
            bare_match = BARE_ITEM_TOTAL_RE.fullmatch(evidence_text.strip())
            raw_total = (
                total_match.group(1)
                if total_match
                else bare_match.group(1)
                if bare_match
                else None
            )
            if raw_total is not None:
                total = int(raw_total)
                evidence["teacher_item_total"] = total
                if 1 <= total <= 20:
                    proposal = {
                        "schema_version": "1.0",
                        "operation": "set_item_total_override",
                        "category": category,
                        "affected_id": exception.get("affected_id"),
                        "printed_marks": total,
                        "reinterpretation_method": "deterministic_teacher_item_total",
                    }
                    return (
                        proposal,
                        (
                            f"Override the printed item total for Question {affected} "
                            f"to {total} marks."
                        ),
                        evidence,
                    )

        normalised = re.sub(r"\\s*[;|]\\s*", "\\n", evidence_text.strip())
        points = parse_mark_points(normalised)
        total, _ = effective_mark_total(points, normalised)
        evidence["parsed_mark_points"] = points
        evidence["parsed_mark_total"] = total
        if not points or total <= 0:
            return None, None, evidence
        if any(
            int(item.get("count") or 0) <= 0
            or not str(item.get("descriptor") or "").strip()
            for item in points
        ):
            return None, None, evidence
        proposal = {
            "schema_version": "1.0",
            "operation": "replace_mark_points",
            "category": category,
            "affected_id": exception.get("affected_id"),
            "mark_points": points,
            "expected_total": total,
            "reinterpretation_method": "deterministic_teacher_mark_scheme",
        }
        return (
            proposal,
            f"Use the teacher-confirmed {total}-mark scheme for Question {affected}.",
            evidence,
        )

'''
    text = text[:start] + new_block + text[end:]
    return text


def patch_tests(text: str) -> str:
    addition = r'''
def test_item_total_teacher_override_accepts_plain_language():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.1.1"},
        "award 3 marks",
    )
    assert proposal["operation"] == "set_item_total_override"
    assert proposal["printed_marks"] == 3
    assert proposal["reinterpretation_method"] == "deterministic_teacher_item_total"
    assert evidence["teacher_item_total"] == 3
    assert "3 marks" in display


def test_item_total_teacher_override_accepts_parenthesised_total():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.1.1"},
        "(3)",
    )
    assert proposal["operation"] == "set_item_total_override"
    assert proposal["printed_marks"] == 3
    assert evidence["teacher_item_total"] == 3
    assert "3 marks" in display


def test_item_total_override_reconciles_printed_two_to_computed_three():
    normalised = _normalised_rows([
        ["11.1.1", "working", "1A one\\n1A two\\n1A three", "(2)"],
    ])
    structure = {
        "questions": [_q("11.1.1", 0, printed=2, computed=3, points=[
            {"count": 1, "descriptor": "one"},
            {"count": 1, "descriptor": "two"},
            {"count": 1, "descriptor": "three"},
        ])],
        "exceptions": [{
            "level": "red",
            "category": "item_total_mismatch",
            "affected_id": "11.1.1",
            "message": "prints 2 but computes 3",
            "suggestions": [],
        }],
        "subtotals": [],
        "summary": {},
    }
    patch = phase7_5_deterministic_proposal(
        {"category": "item_total_mismatch", "affected_id": "11.1.1"},
        "award 3 marks",
    )[0]
    applied, issue, handled = apply_phase7_5_patch(
        structure,
        normalised,
        correction_id="corr-11-1-1",
        category="item_total_mismatch",
        affected_id="11.1.1",
        operation=patch["operation"],
        patch=patch,
    )
    assert handled is True
    assert issue is None
    assert applied["source_printed_marks"] == 2
    assert applied["printed_marks"] == 3
    assert structure["questions"][0]["printed_marks"] == 3
    assert structure["questions"][0]["computed_shorthand_marks"] == 3
    assert structure["exceptions"] == []
'''
    if "test_item_total_teacher_override_accepts_plain_language" in text:
        raise RuntimeError("item-total tests already present")
    return text.rstrip() + "\n\n" + addition.strip() + "\n"


def patch_html(text: str) -> str:
    text = replace_once(
        text,
        "PBHS Mathematics — Phase 7.5 Review v4",
        "PBHS Mathematics — Phase 7.5 Review v4.1",
        "review title",
    )

    text = replace_once(
        text,
        "select('id,exception_id,input_kind,display_text,proposed_patch,confirmation_status,created_at,updated_at')",
        "select('id,exception_id,input_kind,typed_text,display_text,proposed_patch,confirmation_status,created_at,updated_at')",
        "pending correction select",
    )

    recovery = r'''async function unresolvedEventFor(correctionId){
 const r=await sb.from('job_events').select('event_type,payload,created_at').eq('job_id',jobId).eq('event_type','phase7_correction_reinterpretation_unresolved').order('created_at',{ascending:false}).limit(50);
 if(r.error)throw r.error;
 return (r.data||[]).find(e=>e.payload?.correction_id===correctionId)||null;
}
async function retrySavedInterpretation(corr){
 const failed=await unresolvedEventFor(corr.id);
 if(!failed)return await waitProposal(corr.id,new Date(corr.created_at));
 status('The saved correction could not be interpreted previously. Retrying it with the updated Phase 7.5 interpreter…','warn');
 const startedAt=new Date();
 const rr=await invoke('retry-correction-reinterpretation',{correction_id:corr.id});
 log('RETRIED SAVED INTERPRETATION',{correction_id:corr.id,result:rr,typed_text:corr.typed_text});
 return await waitProposal(corr.id,startedAt);
}
'''
    text = replace_once(
        text,
        "async function waitProposal(correctionId,submittedAt){",
        recovery + "async function waitProposal(correctionId,submittedAt){",
        "recovery helpers",
    )

    old_show = '''function showProposal(corr){currentCorrection=corr;$('#choices').classList.add('hide');$('#proposalPanel').classList.remove('hide');const p=corr.proposed_patch||{};$('#proposalText').innerHTML=`<b>${esc(corr.display_text||'Structured correction ready.')}</b><br><br><code>${esc(p.operation||'awaiting reinterpretation')}</code>${p.target_id?` → <b>${esc(p.target_id)}</b>`:''}${p.expected_total!=null?`<br>Expected total: <b>${esc(p.expected_total)}</b>`:''}`;status('Show-back ready. Confirm only if this matches what you intended.','success')}'''
    new_show = '''function showProposal(corr){currentCorrection=corr;$('#choices').classList.add('hide');$('#proposalPanel').classList.remove('hide');const p=corr.proposed_patch||{};$('#proposalText').innerHTML=`<b>${esc(corr.display_text||'Structured correction ready.')}</b><br><br><code>${esc(p.operation||'awaiting reinterpretation')}</code>${p.target_id?` → <b>${esc(p.target_id)}</b>`:''}${p.expected_total!=null?`<br>Expected total: <b>${esc(p.expected_total)}</b>`:''}${p.printed_marks!=null?`<br>Teacher item total: <b>${esc(p.printed_marks)} marks</b>`:''}`;status('Show-back ready. Confirm only if this matches what you intended.','success')}'''
    text = replace_once(text, old_show, new_show, "proposal item total display")

    old_submit = '''async function submitAndInterpret(body){
 setBusy(true);try{const submittedAt=new Date();const result=await invoke('submit-correction',body);const cid=result.correction?.id;if(!cid)throw new Error('Correction ID missing from submit response.');let corr=result.confirmation_ready?result.correction:await waitProposal(cid,submittedAt);if(!corr.proposed_patch){const f=await sb.from('corrections').select('id,exception_id,input_kind,display_text,proposed_patch,confirmation_status,created_at').eq('id',cid).single();if(f.error)throw f.error;corr=f.data}log('SHOW-BACK READY',corr);showProposal(corr)}finally{setBusy(false)}}'''
    new_submit = '''async function submitAndInterpret(body){
 setBusy(true);try{
  const saved=await pendingCorrection();
  if(saved&&saved.exception_id===body.exception_id){
   status('A saved correction attempt already exists for this item. Resuming that attempt instead of creating a duplicate.','warn');
   await resumePending();return;
  }
  const submittedAt=new Date();const result=await invoke('submit-correction',body);const cid=result.correction?.id;if(!cid)throw new Error('Correction ID missing from submit response.');let corr=result.confirmation_ready?result.correction:await waitProposal(cid,submittedAt);if(!corr.proposed_patch){const f=await sb.from('corrections').select('id,exception_id,input_kind,typed_text,display_text,proposed_patch,confirmation_status,created_at').eq('id',cid).single();if(f.error)throw f.error;corr=f.data}log('SHOW-BACK READY',corr);showProposal(corr)
 }finally{setBusy(false)}}'''
    text = replace_once(text, old_submit, new_submit, "duplicate pending recovery")

    old_resume = '''async function resumePending(){const p=await pendingCorrection();if(!p)return false;const ex=await exceptionById(p.exception_id);currentActive=await activeExceptions();currentException=ex;currentStep=specFor(ex);renderExplanation(ex,currentStep);$('#review').classList.remove('hide');$('#progress').textContent=`Saved pending correction • ${humanCategory(ex.category)}${ex.affected_id?` • ${ex.affected_id}`:''}`;await showEvidence();let corr=p;if(!corr.proposed_patch){status('Your saved correction is still being interpreted. Resuming that work…');corr=await waitProposal(corr.id,new Date(corr.created_at))}showProposal(corr);return true}'''
    new_resume = '''async function resumePending(){const p=await pendingCorrection();if(!p)return false;const ex=await exceptionById(p.exception_id);currentActive=await activeExceptions();currentException=ex;currentStep=specFor(ex);renderExplanation(ex,currentStep);$('#review').classList.remove('hide');$('#progress').textContent=`Saved pending correction • ${humanCategory(ex.category)}${ex.affected_id?` • ${ex.affected_id}`:''}`;await showEvidence();let corr=p;if(!corr.proposed_patch){status('Your saved correction is being interpreted…');corr=await retrySavedInterpretation(corr)}showProposal(corr);return true}'''
    text = replace_once(text, old_resume, new_resume, "resume unresolved correction")

    return text


PATCHERS = {
    "engine/src/memo_engine/phase7_5.py": patch_phase,
    "engine/tests/test_phase7_5_raw_categories.py": patch_tests,
    "docs/phase7-5-review/index.html": patch_html,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    staged: dict[str, str] = {}

    for rel, expected in EXPECTED_BLOB_SHAS.items():
        path = root / rel
        if not path.is_file():
            raise RuntimeError(f"Missing required file: {rel}")
        data = path.read_bytes()
        actual = git_blob_sha(data)
        if actual != expected:
            raise RuntimeError(
                f"Refusing to patch {rel}: expected Git blob {expected}, found {actual}."
            )
        updated = PATCHERS[rel](data.decode("utf-8"))
        if rel.endswith(".py"):
            compile(updated, rel, "exec")
        staged[rel] = updated
        print(f"OK baseline: {rel} {actual}")

    if args.check:
        print("CHECK PASSED — item-total fix is patchable.")
        return 0

    for rel, updated in staged.items():
        (root / rel).write_text(updated, encoding="utf-8", newline="\n")
        print(f"UPDATED: {rel}")

    print("APPLIED — run engine tests and browser JS syntax check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
