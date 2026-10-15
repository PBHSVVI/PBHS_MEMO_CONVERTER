import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
const model = source.split("// BEGIN EFFECTIVE PARENT TOTAL MODEL", 2)[1]
  ?.split("// END EFFECTIVE PARENT TOTAL MODEL", 1)[0];
assert.ok(model, "effective parent total model is present");
const { effectiveChildTotal } = new Function(
  `${model}; return { effectiveChildTotal };`,
)();

const question = (question_id, computed_shorthand_marks, source_block_index) => ({
  question_id,
  computed_shorthand_marks,
  source_block_index,
  mark_points: [],
});
const correction = (id, proposed_patch) => ({ id, proposed_patch });

test("server model uses only the newest effective staged child correction", () => {
  const structure = { questions: [question("1.1", 0, 1), question("1.2", 0, 2)] };
  const corrections = [
    correction("one", { operation: "replace_item_content", target_id: "1.1", expected_total: 4 }),
    correction("old", { operation: "replace_item_content", target_id: "1.2", expected_total: 4 }),
    correction("new", { operation: "replace_item_content", target_id: "1.2", expected_total: 3, supersedes_correction_id: "old" }),
  ];
  assert.equal(effectiveChildTotal(structure, corrections, "1"), 7);
});

test("server model totals current staged children independently of the old exception", () => {
  const structure = { questions: [question("3.1", 0, 1), question("3.2", 0, 2), question("3.3", 0, 3)] };
  const corrections = [
    correction("31", { operation: "replace_item_content", target_id: "3.1", expected_total: 3 }),
    correction("32", { operation: "replace_item_content", target_id: "3.2", expected_total: 2 }),
    correction("33", { operation: "replace_item_content", target_id: "3.3", expected_total: 2 }),
  ];
  assert.equal(effectiveChildTotal(structure, corrections, "3"), 7);
});

test("server model includes insertions, allocation edits and numbering ownership", () => {
  const structure = { questions: [question("4.1", 2, 1), question("5.1", 1, 2)] };
  const corrections = [
    correction("allocation", { operation: "resolve_question_allocation_pairing", allocations: [{ question_id: "4.1", printed_marks: 3 }] }),
    correction("rename", { operation: "rename_question_identifier", affected_id: "5.1", target_id: "4.2", source_block_index: 2 }),
    correction("insert", { operation: "insert_missing_child_question", question_id: "4.3", expected_total: 4 }),
  ];
  assert.equal(effectiveChildTotal(structure, corrections, "4"), 8);
});

test("request path recomputes server state and fails closed on stale totals", () => {
  assert.match(source, /effectiveChildTotal\(structure, confirmedRows \?\? \[\], String\(exception\.affected_id\)\)/);
  assert.match(source, /submittedEffectiveTotal !== serverEffectiveTotal/);
  assert.match(source, /error: "stale_review_state"/);
  assert.doesNotMatch(source, /Number\(match\[1\]\) !== submittedEffectiveTotal/);
});
