import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { callEdge, makeFixture, jobId, uuid } from "./review-flow.fixture.mjs";

const page = readFileSync(new URL("../../../docs/phase7-5-review/index.html", import.meta.url), "utf8");
const extract = (from, to) => page.slice(page.indexOf(from), page.indexOf(to, page.indexOf(from)));
const models = [
  extract("// BEGIN SEMANTIC CONFLICT MODEL", "// END SEMANTIC CONFLICT MODEL"),
  extract("// BEGIN REVIEW DEPENDENCY MODEL", "// END REVIEW DEPENDENCY MODEL"),
  extract("function conclusionDeductionFits", "// END TEACHER DECISION MODEL"),
  extract("function teacherShowBackModel", "// END TEACHER SHOWBACK MODEL"),
  extract("function parseStructuredMarking", "async function submitAllocations"),
  extract("function contentCorrectionEnvelope", "function childRepairEnvelope"),
  extract("function childRepairEnvelope", "function missingChildEnvelope"),
  extract("async function submitChildRepair", "function safeName"),
  extract("function majorQuestionId", "async function stagedCorrections"),
].join("\n");

function reviewModel(fixture, exception) {
  const currentConfirmed = fixture.rows.corrections;
  const context = vm.createContext({
    currentConfirmed, currentStep: {}, currentException: exception, jobId, manualEditQuestion: null, manualEditTarget: "",
    ensureStructure: async () => fixture.structure,
    submitAndInterpret: body => callEdge(fixture, "submit-correction", body),
    boundedItemEditorAllowed: () => true,
  });
  const model = vm.runInContext(models + `
    ({ actionableReviewQueue, familyDecision, proposedMarking, markingProposal, submitContent,
       submitChildRepair, teacherShowBackModel, numberingForQuestion, verifiedEqualityAmendment })
  `, context);
  return model;
}

async function submitted(fixture) {
  const pending = fixture.rows.corrections.filter(row => row.confirmation_status === "pending");
  assert.equal(pending.length, 1);
  assert.equal(pending[0].applied_at, null);
  assert.equal(fixture.rows.jobs[0].status, "correction_pending");
  const response = await callEdge(fixture, "confirm-correction", { correction_id: pending[0].id, defer_revalidation: true });
  const saved = await response.json();
  assert.equal(response.status, 200, JSON.stringify(saved));
  assert.equal(saved.staged, true);
  assert.equal(saved.correction.applied_at, null);
  return saved.correction;
}

test("the ambiguous probability and cards proposals reach show-back, then explicit staging", async () => {
  const fixture = makeFixture();
  for (const [exception, question] of [[fixture.probabilityEx, fixture.structure.questions[0]], [fixture.cardsEx, fixture.structure.questions[1]]]) {
    const browser = reviewModel(fixture, exception);
    const suggestion = exception.suggestions[0];
    const draft = browser.proposedMarking(suggestion);
    const proposal = browser.markingProposal(exception, suggestion, question, fixture.normalized, draft, suggestion.converted_working, null);
    assert.ok(proposal.values, proposal.missing);
    await browser.submitContent(proposal.values);
    const pending = fixture.rows.corrections.at(-1);
    assert.equal(pending.confirmation_status, "pending");
    const preview = browser.teacherShowBackModel(pending);
    assert.equal(preview.expected_total, 4);
    assert.equal(preview.source_block_index, question.source_block_index);
    assert.ok(preview.solution_lines.length);
    if (exception === fixture.probabilityEx) {
      assert.match(preview.question_text, /P\(A∪B\) = 10\/15/);
      assert.equal(proposal.amendment.original, "P(A∪B) = 13/15");
      assert.equal(proposal.amendment.consequence, "P(A∩B) = 1/15");
      const incomplete = browser.markingProposal(exception, suggestion, question, fixture.normalized, draft, [], null);
      assert.match(incomplete.missing, /question wording or correct the working/);
    } else {
      assert.match(preview.question_text, /Show whether the events are independent/);
      assert.equal(preview.mark_points.filter(point => point.descriptor.includes("Withhold this mark")).length, 1);
      assert.equal(preview.mark_points.at(-1).count, 1);
      assert.equal(preview.mark_points.reduce((sum, point) => sum + point.count, 0), 4);
    }
    await submitted(fixture);
  }
});

test("a source comparison gives a complete proposal only for an exact equality", () => {
  const fixture = makeFixture();
  const browser = reviewModel(fixture, fixture.cardsEx);
  const evidence = "The handwritten relation between 10/250 and 1/25 appears to be >, not =.";
  const working = String.raw`P(A)=\frac{10}{250}=\frac{1}{25}=0.04`;
  const amendment = browser.verifiedEqualityAmendment(evidence, [working]);
  assert.equal(amendment.amended, "10/250 = 1/25");
  assert.equal(browser.verifiedEqualityAmendment(evidence, [working.replace("0.04", "0.4")]), null);
});

test("the saved cards question cannot mask page-five numbering or block confirmation", async () => {
  const fixture = makeFixture();
  const cards = fixture.structure.questions[1], { cardsEx, parentEx } = fixture;
  const savedCards = { id: uuid(21), user_id: cardsEx.user_id, job_id: jobId, exception_id: cardsEx.id,
    confirmation_status: "confirmed", confirmed_at: "2026-11-28T09:00:00Z", applied_at: null,
    proposed_patch: { operation: "replace_item_content", target_id: "4.2", source_block_index: cards.source_block_index } };
  fixture.rows.corrections.push(savedCards);
  cardsEx.status = "resolved";
  const before = structuredClone(fixture.rows.corrections);
  const browser = reviewModel(fixture, parentEx);
  const queue = browser.actionableReviewQueue(fixture.rows.exceptions.filter(row => row.status === "open"), fixture.rows.corrections);
  const group = queue.find(row => row.decision_group?.kind === "numbering");
  const family = browser.familyDecision(group, fixture.rows.corrections);
  assert.equal(group.id, parentEx.id);
  const members = Array.from(family.rows.filter(row => !row.saved), row => ({ exception_id: row.exception_id, target_id: row.to }));
  assert.deepEqual(members.map(row => row.target_id), ["6.2", "6.2.1", "6.2.2"]);
  const body = { job_id: jobId, exception_id: group.id, input_kind: "typed", typed_text: "Correct the page-five numbers" };
  const incomplete = await callEdge(fixture, "submit-correction", {
    ...body, family_numbering: { members: members.slice(1) },
  });
  assert.equal((await incomplete.json()).error, "numbering_family_incomplete");
  const response = await callEdge(fixture, "submit-correction", { ...body, family_numbering: { members } });
  assert.equal(response.status, 201);
  const { correction } = await response.json();
  assert.ok(correction.proposed_patch.numbering_members.every(member => member.source_locator.source_page === 5));
  assert.equal(fixture.rows.exceptions.filter(row => row.status === "resolved").length, 2);
  const saved = await submitted(fixture);
  assert.equal(saved.proposed_patch.numbering_members.length, 3);
  assert.equal(fixture.rows.exceptions.filter(row => row.resolved_by_correction_id === saved.id).length, 3);
  assert.deepEqual(fixture.rows.corrections.slice(0, 2), before);
});

test("manual marking follows the saved occurrence, handles invalid input and preserves a pending show-back", async () => {
  const fixture = makeFixture(), { flags, confirmation, parentEx } = fixture;
  const browser = reviewModel(fixture, parentEx);
  const rename = structuredClone(confirmation);
  const fields = { ".childCorrectId": { value: "6.1" }, ".childTotal": { value: "2" }, ".childMarking": { value: "1A Result" } };
  const editor = { dataset: { questionId: "4.1", sourceBlockIndex: "3", teacherInitiated: "true" },
    querySelector: selector => fields[selector] };
  await assert.rejects(browser.submitChildRepair(editor, null, null, flags), /printed 2 marks/);
  assert.equal(fixture.rows.corrections.length, 1);
  fields[".childMarking"].value = "1M Permutations\n1A Result";
  await browser.submitChildRepair(editor, null, null, flags);
  const pending = fixture.rows.corrections.at(-1);
  const preview = browser.teacherShowBackModel(pending);
  assert.equal(preview.target_id, "6.1");
  assert.equal(preview.mark_points.length, 2);
  assert.equal(pending.proposed_patch.numbering_correction_id, confirmation.id);
  assert.equal(pending.proposed_patch.source_locator.source_page, 5);
  assert.equal(pending.proposed_patch.supersedes_correction_id, undefined);
  const blocked = await callEdge(fixture, "submit-correction", { job_id: jobId, exception_id: parentEx.id, input_kind: "typed" });
  assert.equal((await blocked.json()).correction_id, pending.id);
  const saved = await submitted(fixture);
  assert.equal(saved.id, pending.id);
  assert.deepEqual(fixture.rows.corrections[0], rename);
  const foreign = await callEdge(fixture, "submit-correction", { job_id: jobId, exception_id: parentEx.id, input_kind: "typed" }, uuid(99));
  assert.equal(foreign.status, 404);

  // Editing the prompt later keeps the linked marks and supersedes only that amendment.
  await browser.submitContent({ target: "6.1", question: flags, questionText: "In how many orders can five of eight flags be flown?",
    solutionLines: [], markingText: "" });
  const content = await submitted(fixture);
  assert.deepEqual(content.proposed_patch.mark_points, saved.proposed_patch.mark_points);
  assert.equal(content.proposed_patch.supersedes_correction_id, saved.id);
  assert.equal(content.proposed_patch.numbering_correction_id, rename.id);
  assert.deepEqual(fixture.rows.corrections[0], rename);
});
