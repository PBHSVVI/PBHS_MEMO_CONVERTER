import { describe, expect, it } from "vitest";
import { outputPath, reviewUrl } from "./urls";

const jobId = "e0055801-f512-4573-8389-2c084eb43fe2";
const userId = "7699652c-9795-40e6-a730-ac38c18f5a86";

describe("review handoff", () => {
  it("passes the selected job to the accepted review application", () => {
    expect(reviewUrl(jobId, "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/"))
      .toBe(`https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/phase7-5-review/?job_id=${jobId}&v=4.7`);
  });

  it("rejects malformed identifiers before navigation", () => {
    expect(() => reviewUrl("not-a-job", "https://example.test/teacher-app/")).toThrow("Invalid review job ID");
  });
});

describe("private output paths", () => {
  it("uses the authenticated user's private namespace", () => {
    expect(outputPath(userId, jobId, "docx")).toBe(`${userId}/${jobId}/output/memo.docx`);
    expect(outputPath(userId, jobId, "pdf")).toBe(`${userId}/${jobId}/output/memo.pdf`);
  });
});
