import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  metadataDispatchPolicy,
  normalizeTeacherMetadata,
} from "../_shared/teacher-metadata.ts";

test("normalizes an accepted initial payload", () => {
  assert.deepEqual(
    normalizeTeacherMetadata({
      schema_version: "1.0",
      values: { grade_label: "form 5", duration_minutes: 180, subject: " mathematics " },
      confirmed_absent: [],
    }),
    {
      schema_version: "1.0",
      values: { grade_label: "FORM 5", duration_minutes: 180, subject: "MATHEMATICS" },
      confirmed_absent: [],
    },
  );
});

test("rejects unknown and total fields", () => {
  for (const field of ["unknown", "total_marks", "expected_total_marks"]) {
    assert.throws(() => normalizeTeacherMetadata({ values: { [field]: 150 } }));
  }
});

test("rejects malformed and oversized payloads", () => {
  assert.throws(() => normalizeTeacherMetadata([]));
  assert.throws(() => normalizeTeacherMetadata({ values: [] }));
  assert.throws(() => normalizeTeacherMetadata({ values: { subject: "X".repeat(5000) } }));
});

test("permits initial and dedicated metadata review dispatch only", () => {
  assert.equal(metadataDispatchPolicy({ status: "queued", stage: "upload" }, true).mode, "initial");
  assert.equal(metadataDispatchPolicy({ status: "needs_review", stage: "phase8_1b_metadata_review" }, true).mode, "review_resume");
  assert.equal(metadataDispatchPolicy({ status: "needs_review", stage: "phase7_review" }, true).allowed, false);
  assert.equal(metadataDispatchPolicy({ status: "complete", stage: "complete" }, true).allowed, false);
});

test("normal retry reuses stored metadata without mutation", () => {
  assert.equal(metadataDispatchPolicy({ status: "failed_retryable", stage: "worker_failed" }, false).mode, "retry");
  assert.equal(metadataDispatchPolicy({ status: "complete", stage: "complete" }, false).allowed, false);
});


test("dispatch integration keeps ownership, audit and failure-retention guards", () => {
  const source = readFileSync(new URL("./index.ts", import.meta.url), "utf8");
  assert.match(source, /ctx\.supabase[\s\S]*\.from\("jobs"\)/);
  assert.match(source, /event_type: "teacher_metadata_submitted"/);
  assert.match(source, /teacher_metadata_revision: nextRevision/);
  assert.match(source, /status: claimedFromStatus,[\s\S]*stage: restoredStage/);
  assert.match(source, /claimedFromStatus === "needs_review"[\s\S]*claimedFromStage/);
  assert.match(source, /teacher_metadata_retained: hasMetadata/);
  assert.doesNotMatch(source, /status === "complete".*allowed: true/);
});
