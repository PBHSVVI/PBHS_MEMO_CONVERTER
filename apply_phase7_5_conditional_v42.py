#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

EXPECTED_BLOB_SHAS = {
    "engine/src/memo_engine/phase7_5.py": "7aa3ce81e1589cb7b9cf6b0a73d6d01e26eff880",
    "engine/src/memo_engine/canonical.py": "12912e37845c38edf55acca3072383f0e725ce11",
    "engine/tests/test_phase7_5_raw_categories.py": "aa73b3faefe402b809589351849ead03960d2e61",
    "docs/phase7-5-review/index.html": "7e4183bcc01f0d76110d328e1859feb61489bb9e",
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
        '    "item_total_mismatch",\n    "subtotal_sum_unexpected",',
        '    "item_total_mismatch",\n    "correction_mark_total_invalid",\n    "subtotal_sum_unexpected",',
        "reinterpret category",
    )

    text = replace_once(
        text,
        '    total = sum(int(item["count"]) for item in points)\n'
        '    observed = question.get("printed_marks")\n',
        '    teacher_marking_text = "\\n".join(\n'
        '        str(item.get("source") or "").strip()\n'
        '        for item in points\n'
        '        if str(item.get("source") or "").strip()\n'
        '    )\n'
        '    total, calc_mode = effective_mark_total(points, teacher_marking_text)\n'
        '    observed = question.get("printed_marks")\n',
        "mark total calculation",
    )

    text = replace_once(
        text,
        '    question["computed_shorthand_marks"] = total\n'
        '    question["mark_calculation_mode"] = "teacher_confirmed"\n',
        '    question["computed_shorthand_marks"] = total\n'
        '    question["mark_calculation_mode"] = calc_mode\n',
        "mark calculation mode",
    )

    text = replace_once(
        text,
        '        "mark_total": total,\n'
        '        "source_block_index": question.get("source_block_index"),',
        '        "mark_total": total,\n'
        '        "mark_calculation_mode": calc_mode,\n'
        '        "source_block_index": question.get("source_block_index"),',
        "applied payload mode",
    )

    text = replace_once(
        text,
        '        category in {"mark_arithmetic_mismatch", "item_total_mismatch"}\n'
        '        and operation == "replace_mark_points"\n',
        '        category in {\n'
        '            "mark_arithmetic_mismatch",\n'
        '            "item_total_mismatch",\n'
        '            "correction_mark_total_invalid",\n'
        '        }\n'
        '        and operation == "replace_mark_points"\n',
        "dispatcher categories",
    )

    text = replace_once(
        text,
        '    if category in {"mark_arithmetic_mismatch", "item_total_mismatch"}:\n'
        '        if category == "item_total_mismatch":',
        '    if category in {\n'
        '        "mark_arithmetic_mismatch",\n'
        '        "item_total_mismatch",\n'
        '        "correction_mark_total_invalid",\n'
        '    }:\n'
        '        if category == "item_total_mismatch":',
        "proposal categories",
    )

    text = replace_once(
        text,
        '        total, _ = effective_mark_total(points, normalised)\n'
        '        evidence["parsed_mark_points"] = points\n'
        '        evidence["parsed_mark_total"] = total',
        '        total, calc_mode = effective_mark_total(points, normalised)\n'
        '        evidence["parsed_mark_points"] = points\n'
        '        evidence["parsed_mark_total"] = total\n'
        '        evidence["parsed_mark_calculation_mode"] = calc_mode',
        "proposal total mode",
    )

    text = replace_once(
        text,
        '            "expected_total": total,\n'
        '            "reinterpretation_method": "deterministic_teacher_mark_scheme",',
        '            "expected_total": total,\n'
        '            "mark_calculation_mode": calc_mode,\n'
        '            "reinterpretation_method": "deterministic_teacher_mark_scheme",',
        "proposal mode payload",
    )
    return text


def patch_canonical(text: str) -> str:
    old = '''    partial_credit_rules: list[dict[str, Any]] = []
    if (
        source_branch_count == 1
        and len(parsed_mark_branches) > 1
        and qdata.get("mark_calculation_mode") == "alternative_max"
    ):
'''
    new = '''    partial_credit_rules: list[dict[str, Any]] = []

    # Conditional accuracy thresholds are mutually exclusive, not additive.
    # Example: 2A for 3 correct answers; 1A for 2 correct answers.
    if (
        source_branch_count == 1
        and len(parsed_mark_branches) == 1
        and qdata.get("mark_calculation_mode") == "conditional_accuracy"
    ):
        conditional_points = list(parsed_mark_branches[0])
        counts = [int(point.get("count") or 0) for point in conditional_points]
        max_total = max(counts or [0])
        observed = qdata.get("printed_marks")
        expected_max = (
            int(observed)
            if observed is not None
            else int(qdata.get("computed_shorthand_marks") or 0)
        )
        if max_total and (not expected_max or max_total == expected_max):
            primary_index = counts.index(max_total)
            primary = conditional_points[primary_index]
            for idx, point in enumerate(conditional_points):
                if idx == primary_index:
                    continue
                count = int(point.get("count") or 0)
                if count <= 0 or count >= max_total:
                    continue
                partial_credit_rules.append({
                    "count": count,
                    "descriptor": _collapse(point.get("descriptor", "")),
                    "source": _collapse(point.get("source", "")),
                })
            parsed_mark_branches = [[primary]]
            raw_mark_branches = [_collapse(primary.get("source", ""))]
        else:
            issues.append({
                "level": "amber",
                "category": "conditional_accuracy_conflict",
                "affected_id": qid,
                "message": (
                    "Conditional accuracy thresholds do not reconcile with the "
                    "observed item total and require review."
                ),
            })

    if (
        source_branch_count == 1
        and len(parsed_mark_branches) > 1
        and qdata.get("mark_calculation_mode") == "alternative_max"
    ):
'''
    return replace_once(text, old, new, "canonical conditional accuracy")


def patch_tests(text: str) -> str:
    if "test_conditional_accuracy_correction_is_max_not_sum" in text:
        raise RuntimeError("conditional tests already present")
    addition = r'''

def test_conditional_accuracy_correction_is_max_not_sum():
    proposal, display, evidence = phase7_5_deterministic_proposal(
        {
            "category": "correction_mark_total_invalid",
            "affected_id": "11.1.1",
        },
        "2A for 3 correct answers; 1A for 2 correct answers.",
    )
    assert proposal["operation"] == "replace_mark_points"
    assert proposal["expected_total"] == 2
    assert proposal["mark_calculation_mode"] == "conditional_accuracy"
    assert evidence["parsed_mark_total"] == 2
    assert evidence["parsed_mark_calculation_mode"] == "conditional_accuracy"
    assert "2-mark" in display


def test_conditional_accuracy_overlay_replaces_bad_additive_total():
    normalised = _normalised_rows([
        ["11.1.1", "working", "2A for 3 correct answers\\n1A for 2 correct answers", "(2)"],
    ])
    structure = {
        "questions": [_q(
            "11.1.1", 0, printed=2, computed=3,
            points=[
                {"count": 2, "code": "A", "descriptor": "for 3 correct answers"},
                {"count": 1, "code": "A", "descriptor": "for 2 correct answers"},
            ],
        )],
        "exceptions": [{
            "level": "red",
            "category": "correction_mark_total_invalid",
            "affected_id": "11.1.1",
            "message": "teacher total conflict",
            "suggestions": [],
        }],
        "subtotals": [],
        "summary": {},
    }
    patch = phase7_5_deterministic_proposal(
        {
            "category": "correction_mark_total_invalid",
            "affected_id": "11.1.1",
        },
        "2A for 3 correct answers; 1A for 2 correct answers.",
    )[0]
    applied, issue, handled = apply_phase7_5_patch(
        structure,
        normalised,
        correction_id="corr-conditional",
        category="correction_mark_total_invalid",
        affected_id="11.1.1",
        operation="replace_mark_points",
        patch=patch,
    )
    assert handled is True
    assert issue is None
    assert applied["mark_total"] == 2
    assert applied["mark_calculation_mode"] == "conditional_accuracy"
    assert structure["questions"][0]["computed_shorthand_marks"] == 2
    assert structure["questions"][0]["mark_calculation_mode"] == "conditional_accuracy"
'''
    return text.rstrip() + addition + "\n"


def patch_html(text: str) -> str:
    text = replace_once(
        text,
        "PBHS Mathematics — Phase 7.5 Review v4.1",
        "PBHS Mathematics — Phase 7.5 Review v4.2",
        "version",
    )

    text = replace_once(
        text,
        '<div class="buttonRow"><button id="confirm" class="confirm">Confirm and revalidate</button><button id="pause2" class="secondary">Pause review</button></div>',
        '<div class="buttonRow"><button id="confirm" class="confirm">Confirm and revalidate</button><button id="editProposal" class="secondary">Edit / resubmit</button><button id="pause2" class="secondary">Pause review</button></div>',
        "edit proposal button",
    )

    panel = '''    <div id="recoveryPanel" class="choiceBlock hide">
      <b>Correction interpretation needs attention</b>
      <div id="recoveryMessage" class="muted" style="margin:6px 0 10px"></div>
      <div class="buttonRow">
        <button id="retryInterpretation" class="primary">Retry interpretation</button>
        <button id="editResubmit" class="secondary">Edit / resubmit correction</button>
        <button id="cancelCorrection" class="dangerLite">Cancel this correction attempt</button>
      </div>
    </div>

'''
    text = replace_once(
        text,
        '    <div class="pauseNote"><b>Pause/resume:</b> closing the page does not lose the job. A submitted-but-unconfirmed proposal also remains saved.</div>',
        panel + '    <div class="pauseNote"><b>Pause/resume:</b> closing the page does not lose the job. A submitted-but-unconfirmed proposal also remains saved.</div>',
        "recovery panel",
    )

    helper = r'''
function showRecovery(corr,message){
 currentCorrection=corr;
 $('#choices').classList.add('hide');
 $('#proposalPanel').classList.add('hide');
 $('#recoveryPanel').classList.remove('hide');
 $('#recoveryMessage').textContent=message||'The submitted evidence could not yet be converted into a safe structured correction.';
 status('Your evidence is saved. Retry it, edit/resubmit it, or cancel this attempt.','warn');
}
async function rejectAndReopen(prefill=''){
 if(!currentCorrection)return;
 const ex=currentException||await exceptionById(currentCorrection.exception_id);
 await invoke('reject-correction',{correction_id:currentCorrection.id});
 currentCorrection=null;
 currentActive=await activeExceptions();
 await showException(ex);
 if(prefill)$('#typedText').value=prefill;
}
async function retryCurrentInterpretation(){
 if(!currentCorrection)return;
 setBusy(true);
 try{
  const startedAt=new Date();
  const r=await invoke('retry-correction-reinterpretation',{correction_id:currentCorrection.id});
  log('MANUAL RETRY INTERPRETATION',r);
  const corr=await waitProposal(currentCorrection.id,startedAt);
  if(corr)showProposal(corr);
 }finally{setBusy(false)}
}
'''
    text = replace_once(
        text,
        "async function unresolvedEventFor(correctionId){",
        helper + "async function unresolvedEventFor(correctionId){",
        "recovery helpers",
    )

    text = replace_once(
        text,
        "const bad=(ev.data||[]).find(e=>e.payload?.correction_id===correctionId&&new Date(e.created_at)>=submittedAt);if(bad)throw new Error('Correction reinterpretation remained unresolved. Try another correction method or provide more explicit evidence.')}",
        "const bad=(ev.data||[]).find(e=>e.payload?.correction_id===correctionId&&new Date(e.created_at)>=submittedAt);if(bad){const fresh=await sb.from('corrections').select('id,exception_id,input_kind,typed_text,display_text,proposed_patch,confirmation_status,created_at,updated_at').eq('id',correctionId).single();if(fresh.error)throw fresh.error;showRecovery(fresh.data,'The interpreter could not safely translate this evidence yet. Your correction has not been applied.');return null;}}",
        "unresolved behavior",
    )

    text = replace_once(
        text,
        "corr=await retrySavedInterpretation(corr)}showProposal(corr);return true}",
        "corr=await retrySavedInterpretation(corr);if(!corr)return true}showProposal(corr);return true}",
        "resume null",
    )

    text = replace_once(
        text,
        "let corr=result.confirmation_ready?result.correction:await waitProposal(cid,submittedAt);if(!corr.proposed_patch){",
        "let corr=result.confirmation_ready?result.correction:await waitProposal(cid,submittedAt);if(!corr)return;if(!corr.proposed_patch){",
        "submit null",
    )

    text = replace_once(
        text,
        "function showProposal(corr){currentCorrection=corr;$('#choices').classList.add('hide');$('#proposalPanel').classList.remove('hide');",
        "function showProposal(corr){currentCorrection=corr;$('#recoveryPanel').classList.add('hide');$('#choices').classList.add('hide');$('#proposalPanel').classList.remove('hide');",
        "proposal hides recovery",
    )

    text = replace_once(
        text,
        "function renderChoices(ex){\n currentCorrection=null;$('#proposalPanel').classList.add('hide');$('#choices').classList.remove('hide');",
        "function renderChoices(ex){\n currentCorrection=null;$('#recoveryPanel').classList.add('hide');$('#proposalPanel').classList.add('hide');$('#choices').classList.remove('hide');",
        "choices hide recovery",
    )

    text = replace_once(
        text,
        "function setBusy(v){for(const id of ['submitTyped','submitPhoto','submitFile','confirm','start']){",
        "function setBusy(v){for(const id of ['submitTyped','submitPhoto','submitFile','confirm','start','retryInterpretation','editResubmit','cancelCorrection','editProposal']){",
        "busy buttons",
    )

    hooks = r'''
$('#retryInterpretation').onclick=()=>retryCurrentInterpretation().catch(e=>{log('RETRY ERROR',{message:e.message});status('Retry failed: '+e.message,'error')});
$('#editResubmit').onclick=()=>{const t=currentCorrection?.typed_text||'';rejectAndReopen(t).catch(e=>{log('EDIT/RESUBMIT ERROR',{message:e.message});status('Could not reopen the correction: '+e.message,'error')})};
$('#cancelCorrection').onclick=()=>rejectAndReopen('').catch(e=>{log('CANCEL CORRECTION ERROR',{message:e.message});status('Could not cancel the correction attempt: '+e.message,'error')});
$('#editProposal').onclick=()=>{const t=currentCorrection?.typed_text||'';rejectAndReopen(t).catch(e=>{log('EDIT PROPOSAL ERROR',{message:e.message});status('Could not reopen the correction: '+e.message,'error')})};
'''
    text = replace_once(
        text,
        "$('#confirm').onclick=async()=>{",
        hooks + "$('#confirm').onclick=async()=>{",
        "button hooks",
    )

    text = replace_once(
        text,
        "  case 'mark_arithmetic_mismatch': return {title:`Check Question ${a} mark arithmetic`,what:ex.message||'The marking-point arithmetic does not match the printed total.',need:'Provide the intended marking-point breakdown or corrected total.'};",
        "  case 'mark_arithmetic_mismatch': return {title:`Check Question ${a} mark arithmetic`,what:ex.message||'The marking-point arithmetic does not match the printed total.',need:'Provide the intended marking-point breakdown or corrected total.'};\n"
        "  case 'correction_mark_total_invalid': return {title:`Clarify Question ${a} marking rule`,what:ex.message||'The previous correction could not be reconciled with the marking rule.',need:'Describe the actual scoring rule in normal teacher language. Conditional rules such as “2A for 3 correct; 1A for 2 correct” are alternatives, not marks to add together.'};",
        "conditional explanation",
    )
    return text


PATCHERS = {
    "engine/src/memo_engine/phase7_5.py": patch_phase,
    "engine/src/memo_engine/canonical.py": patch_canonical,
    "engine/tests/test_phase7_5_raw_categories.py": patch_tests,
    "docs/phase7-5-review/index.html": patch_html,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    staged = {}

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
        print("CHECK PASSED — v4.2 patch is applicable.")
        return 0

    for rel, updated in staged.items():
        (root / rel).write_text(updated, encoding="utf-8", newline="\n")
        print(f"UPDATED: {rel}")

    print("APPLIED — run tests and JS syntax check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
