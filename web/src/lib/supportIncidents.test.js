import { describe, expect, it } from "vitest";
import { fallbackJobReference, incidentSnapshot, safeErrorCode, safeText, submitSupportIncident } from "./supportIncidents";

describe("support incident safe snapshot", () => {
  it("captures bounded diagnostic references without memo content", () => {
    const snapshot = incidentSnapshot({
      user: { id: "teacher-1" },
      job: { id: "job-1", source_filename: "Paper 1 Memo.pdf", stage: "structure", status: "needs_review", review_required: true, error_code: "SAFE_ERROR_1" },
      currentView: "review",
      questionContext: "4.2.2",
      unresolvedExceptionCount: 3,
      appVersion: "commit-abc",
    });
    expect(snapshot).toMatchObject({ user_id: "teacher-1", job_id: "job-1", source_filename: "Paper 1 Memo.pdf", current_view: "review", question_context: "4.2.2", unresolved_exception_count: 3, latest_safe_error: "SAFE_ERROR_1" });
    expect(JSON.stringify(snapshot)).not.toContain("memo_content");
  });

  it.each(["sb_secret_example", "Bearer abc", "access_token=abc", "password=hunter2", "https://example/auth/v1/verify?token_hash=abc"])("redacts sensitive text: %s", (value) => {
    expect(safeText(value, 1200)).toBeNull();
    expect(safeErrorCode(value)).toBeNull();
  });

  it("uses a friendly fallback job reference", () => {
    expect(fallbackJobReference("a284e625-6a71-43bd-ac81-7679a29de421")).toBe("JOB-A284E625");
  });

  it("keeps a saved incident successful when notification throws", async () => {
    const single = async () => ({ data: { id: "incident-1", reference: "PBHS-20261013-AB12" }, error: null });
    const client = {
      from: () => ({ insert: () => ({ select: () => ({ single }) }) }),
      functions: { invoke: async () => { throw new Error("offline"); } },
    };
    const result = await submitSupportIncident({
      client, user: { id: "teacher-1" }, incidentType: "stuck", teacherNote: "Please help",
      context: { currentView: "review", appVersion: "test" },
    });
    expect(result.reference).toBe("PBHS-20261013-AB12");
    expect(result.notification_delayed).toBe(true);
  });
});
