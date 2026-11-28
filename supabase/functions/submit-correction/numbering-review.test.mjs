import assert from "node:assert/strict";
import test from "node:test";
import { familyNumberingSelection, matchingNumberingMember, numberingConflict } from "../_shared/numbering-review.mjs";

const exception = (id, printed, offset) => ({
  id, affected_id: printed, category: "question_parent_heading_mismatch",
  suggestions: [{ source_question_id: printed, source_page: 5, source_block_index: 3,
    character_offset: offset, heading_question_id: "6" }],
});
const parent = exception("remaining-parent", "4.2", 100);
const child = exception("remaining-child", "4.2.1", 120);
const questions = [
  { question_id: "4.2", source_page: 3, source_heading_major: "4", source_block_index: 2, source_character_offset: 100 },
  { question_id: "4.2", source_page: 5, source_heading_major: "6", source_block_index: 3, source_character_offset: 100 },
  { question_id: "4.2.1", source_page: 5, source_heading_major: "6", source_block_index: 3, source_character_offset: 120 },
];
const remaining = [
  { exception_id: parent.id, target_id: "6.2" },
  { exception_id: child.id, target_id: "6.2.1" },
];
const saved = { operation: "rename_question_identifier", affected_id: "4.1", target_id: "6.1",
  source_block_index: 3, source_locator: { source_page: 5, parent_heading: "6", source_character_offset: 70 } };

test("the complete remaining family resolves by occurrence and leaves a prior rename alone", () => {
  const { selections } = familyNumberingSelection(parent, [parent, child], questions, remaining);
  assert.deepEqual(selections.map(row => [row.source.printed, row.question.source_page, row.target]),
    [["4.2", 5, "6.2"], ["4.2.1", 5, "6.2.1"]]);
  const patch = { operation: "rename_question_family", numbering_members:
    selections.map(item => ({ affected_id: item.source.printed, target_id: item.target, source_block_index: item.source.block })) };
  assert.equal(numberingConflict(patch, saved), false);
  assert.equal(numberingConflict(patch, { ...saved, target_id: "6.2" }), true);
  assert.equal(familyNumberingSelection(parent, [parent, child], questions, remaining.slice(0, 1)).error, "numbering_family_incomplete");
  assert.equal(familyNumberingSelection(parent, [parent, child], questions,
    [remaining[0], { ...remaining[1], target_id: "6.7.1" }]).error, "numbering_family_invalid_parent");
});

test("saved or applied parent is validated even when its exception is still open", () => {
  const savedParent = { ...saved, affected_id: "4.2", target_id: "6.7",
    source_locator: { ...saved.source_locator, source_character_offset: 100 } };
  const requested = [{ ...remaining[1], target_id: "6.7.1" }];
  for (const applied of [false, true]) {
    const rows = questions.map(q => applied && q.question_id === "4.2" && q.source_page === 5
      ? { ...q, source_question_id: q.question_id, question_id: "6.7" } : q);
    const confirmed = [{ id: "saved", proposed_patch: savedParent, applied_at: applied ? "2026-11-28" : null }];
    assert.equal(familyNumberingSelection(child, [parent, child], rows, requested, confirmed).selections.length, 1);
    assert.equal(familyNumberingSelection(child, [parent, child], rows, remaining.slice(1), confirmed).error,
      "numbering_family_invalid_parent");
    assert.equal(familyNumberingSelection(child, [parent, child], [...rows, { question_id: "6.7.1" }], requested, confirmed).error,
      "numbering_identifier_conflict");
  }
});

test("marking follows the saved rename only when the source and destination match exactly", () => {
  assert.equal(matchingNumberingMember(saved, "4.1", "6.1", 3), saved);
  assert.equal(matchingNumberingMember(saved, "4.1", "6.1", 2), null);
  assert.equal(matchingNumberingMember(saved, "4.1", "6.2", 3), null);
  assert.equal(matchingNumberingMember({ ...saved, operation: "replace_item_content" }, "4.1", "6.1", 3), null);
});
