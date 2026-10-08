import { describe, expect, it, vi } from "vitest";
import { createAndDispatchJob, fetchOutput, retryJob } from "./memoService";

const user = { id: "7699652c-9795-40e6-a730-ac38c18f5a86" };
const job = {
  id: "e0055801-f512-4573-8389-2c084eb43fe2",
  user_id: user.id,
  status: "queued",
  stage: "upload",
};

function uploadClient(order) {
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
    return { data: { status: "dispatched" }, error: null };
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
    });

    expect(order).toEqual(["job", "upload", "dispatch"]);
    expect(client.spies.insert).toHaveBeenCalledWith(expect.objectContaining({
      id: job.id,
      user_id: user.id,
      status: "queued",
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
        teacher_metadata: { schema_version: "1.0", values: {}, confirmed_absent: [] },
      },
    });
    expect(result.status).toBe("dispatched");
  });

  it("uses the same authenticated dispatch contract for a retry", async () => {
    const client = { functions: { invoke: vi.fn(async () => ({ data: { status: "dispatched" }, error: null })) } };
    await retryJob(client, job.id);
    expect(client.functions.invoke).toHaveBeenCalledWith("dispatch-memo", { body: { job_id: job.id } });
  });
});

describe("private downloads", () => {
  it("requests the authenticated user's output object and does not create a public URL", async () => {
    const download = vi.fn(async () => ({ data: new Blob(["docx"]), error: null }));
    const client = { storage: { from: vi.fn(() => ({ download })) } };
    await fetchOutput(client, user.id, job.id, "docx");
    expect(download).toHaveBeenCalledWith(`${user.id}/${job.id}/output/memo.docx`);
    expect(client.storage.from).toHaveBeenCalledWith("memo-files");
  });
});
