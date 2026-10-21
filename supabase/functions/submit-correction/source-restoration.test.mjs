import assert from "node:assert/strict";
import test from "node:test";
import {
  correctionPredecessorMatchesSource,
  sourceHasDirectMarkAllocation,
  validateSourceRestoration,
} from "../_shared/source-restoration.mjs";
import { immutableSourceStateForQuestionOccurrence } from "../_shared/immutable-source-state.mjs";
import { immutableSourceStateForQuestionOccurrence as browserImmutableSourceState } from "../../../docs/phase7-5-review/immutable-source-state.js";

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
  immutableSource: structuralParent,
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
  assert.equal(validateSourceRestoration(request({ immutableSource: marked })).error, "source_has_direct_mark_allocation");
});

test("Q5.2 restoration uses immutable normalized source instead of corrected current structure", () => {
  const normalized = { content: { units: [{ type: "table", rows: [[
    { text: "5.1 First item\n5.2 Parent item\n5.2.1 Child one\n5.2.2 Child two" },
    { text: "solutions" },
    { text: "8A first\n2A child one\n2A child two" },
    { text: "(8)\n(2)\n(2)" },
  ]] }] } };
  const correctedCurrent = {
    question_id: "5.2", source_block_index: 0, printed_marks: 2,
    computed_shorthand_marks: 2, mark_points: [{ count: 2, code: "A" }],
  };
  const immutableSource = immutableSourceStateForQuestionOccurrence(normalized, "5.2", 0);
  const browserSource = browserImmutableSourceState(normalized, "5.2", 0);
  assert.equal(sourceHasDirectMarkAllocation(correctedCurrent), true);
  assert.deepEqual(immutableSource, browserSource);
  assert.deepEqual(immutableSource, {
    question_id: "5.2", source_block_index: 0, source_page: null,
    printed_marks: null, computed_shorthand_marks: null, mark_points: [],
    structural_parent: true, has_direct_marks: false,
  });
  assert.equal(validateSourceRestoration(request({ targetId: "5.2", replacementId: "5.2", immutableSource })).ok, true);
});

test("immutable source resolver blocks erasing an ordinary scored source item", () => {
  const normalized = { content: { units: [{ type: "table", rows: [[
    { text: "2.1 Calculate the value" }, { text: "answer" },
    { text: "1A correct answer" }, { text: "(1)" },
  ]] }] } };
  const immutableSource = immutableSourceStateForQuestionOccurrence(normalized, "2.1", 0);
  assert.equal(immutableSource?.has_direct_marks, true);
  assert.equal(validateSourceRestoration(request({ immutableSource })).error, "source_has_direct_mark_allocation");
});

test("applied confirmed predecessor remains revisable for its exact source occurrence", () => {
  const prior = {
    confirmation_status: "confirmed",
    applied_at: "2026-10-20T09:27:32Z",
    proposed_patch: {
      operation: "replace_item_content",
      target_id: "5.2",
      source_block_index: 3,
    },
  };
  assert.equal(correctionPredecessorMatchesSource({
    prior,
    targetId: "5.2",
    questionSourceIndex: 3,
    matchingOccurrenceCount: 2,
  }), true);
  assert.equal(correctionPredecessorMatchesSource({
    prior,
    targetId: "5.2",
    questionSourceIndex: 8,
    matchingOccurrenceCount: 2,
  }), false);
});

test("legacy predecessor without a locator is accepted only for a unique identifier", () => {
  const prior = {
    confirmation_status: "confirmed",
    proposed_patch: { operation: "replace_item_content", target_id: "5.2" },
  };
  assert.equal(correctionPredecessorMatchesSource({ prior, targetId: "5.2", questionSourceIndex: 3, matchingOccurrenceCount: 1 }), true);
  assert.equal(correctionPredecessorMatchesSource({ prior, targetId: "5.2", questionSourceIndex: 3, matchingOccurrenceCount: 2 }), false);
});

test("submit contract creates an auditable source restoration instead of a zero-mark scheme", async () => {
  const source = await import("node:fs/promises").then(({ readFile }) =>
    readFile(new URL("./index.ts", import.meta.url), "utf8"));
  assert.match(source, /operation: "withdraw_confirmed_correction"/);
  assert.match(source, /source_restoration: true/);
  assert.match(source, /supersession_reason: "teacher_restored_source_state"/);
  assert.doesNotMatch(source, /mark_points:\s*\[\]/);
  assert.match(source, /priorIsEffective/);
  assert.match(source, /immutableSourceStateForQuestionOccurrence/);
  assert.match(source, /internal\/normalized\.json/);
});
