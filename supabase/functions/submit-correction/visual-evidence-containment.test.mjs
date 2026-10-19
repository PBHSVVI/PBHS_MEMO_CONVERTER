import assert from "node:assert/strict";
import test from "node:test";
import { classifyVisualReviewUnit, ensureVisualEvidenceIds, legacyVisualEvidenceId } from "../_shared/visual-evidence.mjs";
import fs from "node:fs";

const observation = (index, text = `4.2.${index}`) => ({
  question_ref: "4.2.1",
  owned_question_ref: "4.2.1",
  association_status: "cross_anchor_mismatch",
  kind: "answer_working",
  transcription: text,
  normalized_math: text,
  confidence: 0.97,
  page: 5,
  source_page_bbox: [index, 1, index + 1, 2],
  rendered_asset_ref: "internal/visual/regions/page-0005-q4_2_1.png",
});

test("legacy visual identity is deterministic and preserves stored IDs", async () => {
  const item = observation(1, "x = 2");
  const expected = await legacyVisualEvidenceId(item, 0);
  const first = await ensureVisualEvidenceIds([item]);
  const second = await ensureVisualEvidenceIds([item]);
  assert.equal(first[0].evidence_id, expected);
  assert.equal(second[0].evidence_id, expected);
  assert.equal((await ensureVisualEvidenceIds([{ ...item, evidence_id: "modern" }]))[0].evidence_id, "modern");
});

test("40 item question identifier sequence is runaway", () => {
  const items = [observation(0, "6.4.2"), observation(1, "4.2"), ...Array.from({ length: 38 }, (_, i) => observation(i + 2, `4.2.${i + 1}`))];
  assert.equal(items.length, 40);
  assert.equal(classifyVisualReviewUnit(items), "runaway_model_output");
});

test("submit correction validates displayed unit and explicit subset", () => {
  const source = fs.readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  assert.match(source, /review_unit_evidence_ids/);
  assert.match(source, /selectionMode === "explicit_subset"/);
  assert.match(source, /decision === "REJECT"[\s\S]*completeSelection/);
  assert.match(source, /selected\.length === suppliedIds\.length/);
  assert.match(source, /classifyVisualReviewUnit\(physical\)/);
});