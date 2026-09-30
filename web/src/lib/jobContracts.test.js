import { describe, expect, it } from "vitest";
import {
  MAX_SOURCE_BYTES,
  canDownload,
  canRetry,
  canReview,
  safeFilename,
  teacherStage,
  teacherStatus,
  validateMemoFile,
} from "./jobContracts";

function file(name, size = 20, type = "") {
  return new File(["x".repeat(Math.min(size, 100))], name, { type });
}

describe("memo upload validation", () => {
  it.each(["memo.pdf", "memo.docx", "memo.png", "memo.jpg", "memo.jpeg"])("accepts %s", (name) => {
    expect(validateMemoFile(file(name))).toMatchObject({ ok: true });
  });

  it("rejects unsupported, empty, and oversized files", () => {
    expect(validateMemoFile(file("memo.doc"))).toMatchObject({ ok: false });
    expect(validateMemoFile(new File([], "memo.pdf"))).toMatchObject({ ok: false });
    expect(validateMemoFile({ name: "memo.pdf", size: MAX_SOURCE_BYTES + 1 })).toMatchObject({ ok: false });
  });

  it("sanitises storage filenames while preserving the supported extension", () => {
    expect(safeFilename("Grade 12 / Memo?.PDF")).toBe("Grade-12-Memo.pdf");
  });
});

describe("teacher job states", () => {
  it.each([
    ["queued", "Queued"],
    ["dispatched", "Starting"],
    ["processing", "Converting"],
    ["needs_review", "Needs review"],
    ["correction_pending", "Needs review"],
    ["rendering", "Preparing files"],
    ["complete", "Ready"],
    ["failed_retryable", "Needs retry"],
    ["failed", "Failed"],
  ])("maps %s without exposing an internal phase", (status, label) => {
    expect(teacherStatus({ status }).label).toBe(label);
  });

  it("maps durable stages to teacher language", () => {
    expect(teacherStage({ status: "processing", stage: "ingestion" })).toBe("Reading memo");
    expect(teacherStage({ status: "processing", stage: "semantic_interpretation" })).toBe("Checking structure and mathematics");
    expect(teacherStage({ status: "processing", stage: "rendering" })).toBe("Creating final memo");
  });

  it("gates review, retry, and download actions by durable job status", () => {
    expect(canReview({ status: "needs_review" })).toBe(true);
    expect(canReview({ status: "correction_pending" })).toBe(true);
    expect(canRetry({ status: "failed_retryable" })).toBe(true);
    expect(canRetry({ status: "queued", stage: "dispatch_retry" })).toBe(true);
    expect(canDownload({ status: "complete" })).toBe(true);
    expect(canDownload({ status: "processing" })).toBe(false);
  });

  it("presents a failed initial dispatch as a retry instead of an active queue", () => {
    const job = { status: "queued", stage: "dispatch_retry" };
    expect(teacherStatus(job)).toMatchObject({ label: "Needs retry", tone: "danger" });
    expect(teacherStage(job)).toBe("Waiting to retry");
  });
});
