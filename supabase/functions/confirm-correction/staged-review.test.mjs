import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const confirmSource = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
const submitSource = readFileSync(new URL("../submit-correction/index.ts", import.meta.url), "utf8");
const resumeSource = readFileSync(new URL("../resume-correction/index.ts", import.meta.url), "utf8");
const reviewSource = readFileSync(
  new URL("../../../docs/phase7-5-review/index.html", import.meta.url),
  "utf8",
);

test("ordinary confirmations default to durable staging without dispatch", () => {
  assert.match(confirmSource, /defer_revalidation !== false/);
  assert.match(reviewSource, /defer_revalidation:true/);
  assert.doesNotMatch(reviewSource, /id="confirmApply"/);
  const confirmBody = reviewSource.split("async function confirmCurrent()", 2)[1]
    .split("async function applyStagedBatch", 1)[0];
  assert.doesNotMatch(confirmBody, /resume-correction|monitorProcessing/);
  for (let i = 0; i < 61; i += 1) {
    assert.equal(confirmBody.includes("resume-correction"), false);
  }
});

test("one end-of-queue recheck owns the single workflow dispatch", () => {
  assert.equal((reviewSource.match(/invoke\('resume-correction'/g) ?? []).length, 1);
  assert.match(reviewSource, /ready=staged\.length>0&&remaining===0/);
  assert.equal((resumeSource.match(/actions\/workflows\/process-memo\.yml\/dispatches/g) ?? []).length, 1);
});

test("explicit semantic choices are structured and do not request reinterpretation", () => {
  assert.match(submitSource, /operation: "resolve_mark_semantic_conflict"/);
  assert.match(submitSource, /reinterpretation_method: "structured_semantic_conflict_choice"/);
  assert.match(submitSource, /exceptionStatus = "awaiting_confirmation"/);
});

test("bounded item totals use the structured editor while free text remains interpretable", () => {
  assert.match(submitSource, /\["item_total_mismatch", "mark_arithmetic_mismatch"\]/);
  assert.match(submitSource, /reconciliation_scope: parentReview \? "suspicious_child" : "bounded_item_editor"/);
  assert.match(submitSource, /reinterpretationDispatched = await dispatchReinterpretation/);
  assert.match(submitSource, /if \(proposedPatch === null\)/);
});

test("staged-target conflicts remain fail closed", () => {
  assert.match(confirmSource, /conflicting_staged_correction/);
  assert.match(confirmSource, /stagedTarget\(item\.proposed_patch\) === target/);
});
