import { describe, expect, it, vi } from "vitest";
import { createAndDispatchJob, fetchOutput, listDepartmentPapers, retryJob, sourceObjectExists } from "./memoService";

const user = { id: "7699652c-9795-40e6-a730-ac38c18f5a86" };
const job = {
  id: "e0055801-f512-4573-8389-2c084eb43fe2",
  user_id: user.id,
  status: "queued",
  stage: "upload",
};
const filingMetadata = {
  schema_version: "1.0", subject_scope: "mathematics", form: 4,
  assessment_type: "class_test", term: 4, year: 2026,
  assessment_number: { applicability: "required", value: 2 },
  paper: { applicability: "not_applicable", value: null },
  duration: { value: 45, unit: "minutes", duration_minutes: 45 },
};

function uploadClient(order, dispatchError = null) {
  const single = vi.fn(async () => {
    order.push("job");
    return { data: job, error: null };
  });
  const insert = vi.fn(() => ({ select: () => ({ single }) }));
  const upload = vi.fn(async () => {
    order.push("upload");
    return { error: null };
  });
  const invoke = vi.fn(async () => {
    order.push("dispatch");
    return { data: dispatchError ? null : { status: "dispatched" }, error: dispatchError };
  });
  return {
    from: vi.fn(() => ({ insert })),
    storage: { from: vi.fn(() => ({ upload, download: vi.fn() })) },
    functions: { invoke },
    spies: { insert, upload, invoke },
  };
}

describe("conversion creation", () => {
  it("creates the job, uploads to its private source path, then dispatches only the job id", async () => {
    const order = [];
    const client = uploadClient(order);
    vi.spyOn(crypto, "randomUUID").mockReturnValue(job.id);

    const result = await createAndDispatchJob({
      client,
      user,
      file: new File(["memo"], "Paper 1 Memo.pdf", { type: "application/pdf" }),
      filingMetadata,
      displayName: "Form 4 Class Test 2 Term 4 2026",
    });

    expect(order).toEqual(["job", "upload", "dispatch"]);
    expect(client.spies.insert).toHaveBeenCalledWith(expect.objectContaining({
      id: job.id,
      user_id: user.id,
      status: "queued",
      filing_contract_version: "1.0",
      source_path: `${user.id}/${job.id}/source/Paper-1-Memo.pdf`,
    }));
    expect(client.spies.upload).toHaveBeenCalledWith(
      `${user.id}/${job.id}/source/Paper-1-Memo.pdf`,
      expect.any(File),
      expect.objectContaining({ upsert: false, contentType: "application/pdf" }),
    );
    expect(client.spies.invoke).toHaveBeenCalledWith("dispatch-memo", {
      body: {
        job_id: job.id,
        filing_metadata: filingMetadata,
        display_name: "Form 4 Class Test 2 Term 4 2026",
      },
    });
    expect(result.status).toBe("dispatched");
  });

  it("retains the created job and returns a retryable context when dispatch fails after upload", async () => {
    const order = [];
    const client = uploadClient(order, { message: "HTTP 400" });
    const onJobCreated = vi.fn();
    vi.spyOn(crypto, "randomUUID").mockReturnValue(job.id);
    await expect(createAndDispatchJob({
      client,
      user,
      file: new File(["memo"], "Paper 1 Memo.pdf", { type: "application/pdf" }),
      filingMetadata,
      displayName: "Form 4 Class Test 2 Term 4 2026",
      onJobCreated,
    })).rejects.toMatchObject({
      code: "DISPATCH_FAILED",
      details: { job: expect.objectContaining({ id: job.id, status: "queued", stage: "dispatch_retry" }) },
    });
    expect(order).toEqual(["job", "upload", "dispatch"]);
    expect(onJobCreated).toHaveBeenCalledWith(job);
  });

  it("uses the same authenticated dispatch contract for a retry", async () => {
    const client = { functions: { invoke: vi.fn(async () => ({ data: { status: "dispatched" }, error: null })) } };
    await retryJob(client, job.id);
    expect(client.functions.invoke).toHaveBeenCalledWith("dispatch-memo", { body: { job_id: job.id } });
  });
});

describe("legacy uploaded source recovery", () => {
  it("only confirms a source inside the authenticated job folder", async () => {
    const list = vi.fn(async () => ({ data: [{ name: "Paper-1-Memo.pdf" }], error: null }));
    const client = { storage: { from: vi.fn(() => ({ list })) } };
    const recoverable = { ...job, source_path: `${user.id}/${job.id}/source/Paper-1-Memo.pdf` };
    await expect(sourceObjectExists(client, user.id, recoverable)).resolves.toBe(true);
    expect(list).toHaveBeenCalledWith(`${user.id}/${job.id}/source`, { limit: 10, search: "Paper-1-Memo.pdf" });
    await expect(sourceObjectExists(client, "other-user", recoverable)).resolves.toBe(false);
  });
});

describe("private downloads", () => {
  it("requests the authenticated user's output object and does not create a public URL", async () => {
    const download = vi.fn(async () => ({ data: new Blob(["docx"]), error: null }));
    const client = { storage: { from: vi.fn(() => ({ download })) } };
    const result = await fetchOutput(client, user.id, { ...job, display_name: "Form 4 Test" }, "docx");
    expect(download).toHaveBeenCalledWith(`${user.id}/${job.id}/output/memo.docx`);
    expect(client.storage.from).toHaveBeenCalledWith("memo-files");
    expect(result.filename).toBe("Form 4 Test - GDE Memo.docx");
  });
});

describe("department library", () => {
  it("reads only the trusted summary relation and never other teachers' raw jobs", async () => {
    const limit = vi.fn(async () => ({ data: [{ job_id: "summary" }], error: null }));
    const order = vi.fn(() => ({ limit }));
    const select = vi.fn(() => ({ order }));
    const client = { from: vi.fn(() => ({ select })) };
    await expect(listDepartmentPapers(client)).resolves.toEqual([{ job_id: "summary" }]);
    expect(client.from).toHaveBeenCalledWith("paper_library_summary");
    expect(select.mock.calls[0][0]).toContain("owner_display_name");
    expect(order).toHaveBeenCalledWith("updated_at", { ascending: false });
  });
});
