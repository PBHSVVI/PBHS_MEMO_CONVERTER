import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { normalizeDisplayName, normalizeFilingMetadata } from "../_shared/filing-metadata.ts";

const valid = {
  schema_version: "1.0", subject_scope: "mathematics", form: 4,
  assessment_type: "class_test", term: 4, year: 2026,
  assessment_number: { applicability: "required", value: 2 },
  paper: { applicability: "not_applicable", value: null },
  duration: { value: 45, unit: "minutes", duration_minutes: 45 },
};
const now = new Date("2026-10-14T00:00:00Z");

test("accepts controlled filing data and preserves first-class periods", () => {
  assert.deepEqual(normalizeFilingMetadata(valid, now), valid);
  const periods = { ...valid, duration: { value: 2, unit: "periods", duration_minutes: null } };
  assert.deepEqual(normalizeFilingMetadata(periods, now).duration, periods.duration);
});

test("rejects contradictory assessment number and paper values", () => {
  assert.throws(() => normalizeFilingMetadata({ ...valid, assessment_number: { applicability: "not_applicable", value: null } }, now));
  assert.throws(() => normalizeFilingMetadata({ ...valid, paper: { applicability: "required", value: 2 } }, now));
  const examination = { ...valid, assessment_type: "examination", assessment_number: { applicability: "not_applicable", value: null }, paper: { applicability: "required", value: 2 } };
  assert.deepEqual(normalizeFilingMetadata(examination, now).paper.value, 2);
  assert.throws(() => normalizeFilingMetadata({ ...examination, assessment_number: { applicability: "required", value: 3 } }, now));
});

test("rejects invalid controlled and duration values", () => {
  for (const patch of [
    { subject_scope: "science" }, { form: 7 }, { term: 5 }, { year: 2015 },
    { duration: { value: 0, unit: "minutes", duration_minutes: 0 } },
    { duration: { value: -1, unit: "hours", duration_minutes: -60 } },
    { duration: { value: 1.5, unit: "periods", duration_minutes: null } },
    { duration: { value: 2, unit: "periods", duration_minutes: 120 } },
  ]) assert.throws(() => normalizeFilingMetadata({ ...valid, ...patch }, now));
});

test("display name rejects unsafe, empty and silently-normalized values", () => {
  assert.equal(normalizeDisplayName("Form 4 Class Test 2 Term 4 2026"), "Form 4 Class Test 2 Term 4 2026");
  for (const value of ["", "../memo", "memo/name", "memo<script>", "x".repeat(121)]) assert.throws(() => normalizeDisplayName(value));
});

test("dispatch requires and audits filing data only for opted-in new jobs", () => {
  const source = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  assert.match(source, /filingRequired.*filing_contract_version === "1\.0"/s);
  assert.match(source, /missing_required_filing_contract/);
  assert.match(source, /event_type: "filing_metadata_submitted"/);
  assert.match(source, /claimValues\.filing_metadata = normalizedFiling/);
});

