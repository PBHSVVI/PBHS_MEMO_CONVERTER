import assert from "node:assert/strict";
import test from "node:test";
import {
  sourceHasDirectMarkAllocation,
  validateSourceRestoration,
} from "../_shared/source-restoration.mjs";

const structuralParent = {
  question_id: "2.1",
  printed_marks: null,
  computed_shorthand_marks: 0,
  mark_points: [],
};

const request = (overrides = {}) => ({
  targetId: "2.1",
  replacementId: "2.1",
  printedMarks: null,
  markingText: "",
  supersedesCorrectionId: "b7b8b6cd-6bae-44e0-8960-ba61988654e2",
  priorIsEffective: true,
  question: structuralParent,
  ...overrides,
});

test("blank and explicit zero restore an effective staged correction on a structural parent", () => {
  assert.equal(validateSourceRestoration(request()).ok, true);
  assert.equal(validateSourceRestoration(request({ printedMarks: 0 })).ok, true);
});

test("new, stale, renamed, or nonblank corrections cannot use source restoration", () => {
  assert.equal(validateSourceRestoration(request({ supersedesCorrectionId: "" })).error, "missing_predecessor");
  assert.equal(validateSourceRestoration(request({ priorIsEffective: false })).error, "predecessor_not_effective");
  assert.equal(validateSourceRestoration(request({ replacementId: "2.2" })).error, "target_changed");
  assert.equal(validateSourceRestoration(request({ markingText: "1A value" })).error, "marking_scheme_not_blank");
  assert.equal(validateSourceRestoration(request({ printedMarks: 1 })).error, "total_not_blank_or_zero");
});

test("a source item with genuine marks cannot be erased", () => {
  const marked = { ...structuralParent, printed_marks: 1, computed_shorthand_marks: 1,
    mark_points: [{ count: 1, code: "A", descriptor: "answer" }] };
  assert.equal(sourceHasDirectMarkAllocation(marked), true);
  assert.equal(validateSourceRestoration(request({ question: marked })).error, "source_has_direct_mark_allocation");
});

test("submit contract creates an auditable source restoration instead of a zero-mark scheme", async () => {
  const source = await import("node:fs/promises").then(({ readFile }) =>
    readFile(new URL("./index.ts", import.meta.url), "utf8"));
  assert.match(source, /operation: "withdraw_confirmed_correction"/);
  assert.match(source, /source_restoration: true/);
  assert.match(source, /supersession_reason: "teacher_restored_source_state"/);
  assert.doesNotMatch(source, /mark_points:\s*\[\]/);
  assert.match(source, /priorIsEffective/);
});
