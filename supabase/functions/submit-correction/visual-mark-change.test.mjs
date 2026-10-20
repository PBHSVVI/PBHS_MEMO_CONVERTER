import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const submit = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
const confirm = readFileSync(new URL("../confirm-correction/index.ts", import.meta.url), "utf8");

test("visual mark-change decisions use a bounded structured contract", () => {
  assert.match(submit, /visual_mark_change_resolution/);
  assert.match(submit, /validateVisualMarkChangeUnit/);
  assert.match(submit, /visual_mark_change_member_exception_ids/);
  assert.match(submit, /visual_mark_change_review_unit_id/);
  assert.match(submit, /visual_mark_change_selected_value_mismatch/);
});

test("matching use and reject are non-destructive while genuine changes remain strict", () => {
  assert.match(submit, /operation: "resolve_visual_mark_change"/);
  assert.match(submit, /visual_mark_change_marking_scheme_required/);
  assert.match(submit, /effectiveVisualItemState/);
  assert.match(submit, /visual_mark_change_effective_total_mismatch/);
  assert.match(submit, /visual_mark_change_matches_effective_total: validated\.decision === "USE"/);
  assert.match(submit, /\["USE", "MANUAL"\]/);
  assert.match(submit, /parsed\.total !== printedMarks/);
});

test("server validates the complete logical unit instead of trusting the browser", () => {
  assert.match(submit, /exactMembers/);
  assert.match(submit, /exactCandidates/);
  assert.match(submit, /visual_mark_change_unit_changed/);
  assert.match(submit, /visual_mark_change_evidence_mismatch/);
  assert.match(submit, /linkedEvidenceIds/);
  assert.match(submit, /sourceBlockIndex/);
  assert.match(submit, /Number\(entry\.source_block_index\) === Number\(sourceBlockIndex\)/);
});

test("confirmation resolves every member row while preserving it for audit", () => {
  assert.match(confirm, /visualMarkMembers/);
  assert.match(confirm, /resolved_by_correction_id: correctionId/);
  assert.match(confirm, /\.in\("id", visualMarkMembers\)/);
  assert.doesNotMatch(confirm, /delete\(\).*visualMarkMembers/s);
});
