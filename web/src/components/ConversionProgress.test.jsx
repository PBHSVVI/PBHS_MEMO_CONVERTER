import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConversionProgress } from "./ConversionProgress";

const user = { id: "7699652c-9795-40e6-a730-ac38c18f5a86" };
const base = {
  id: "e0055801-f512-4573-8389-2c084eb43fe2",
  user_id: user.id,
  source_filename: "Paper 1 Memo.pdf",
  stage: "complete",
  created_at: "2026-09-29T06:52:00Z",
  updated_at: "2026-09-29T06:53:20Z",
};

function clientFor(job) {
  const single = vi.fn(async () => ({ data: job, error: null }));
  const invoke = vi.fn(async () => ({ data: { status: "dispatched" }, error: null }));
  const download = vi.fn(async () => ({ data: new Blob(["file"]), error: null }));
  return {
    from: vi.fn(() => ({
      select: () => ({
        eq: () => ({ single }),
      }),
    })),
    functions: { invoke },
    storage: { from: vi.fn(() => ({ download })) },
  };
}

describe("conversion outcomes", () => {
  it("routes needs-review jobs to the accepted review page with the selected id", async () => {
    const job = { ...base, status: "needs_review", stage: "phase7_review" };
    render(<ConversionProgress client={clientFor(job)} user={user} initialJob={job} onBack={() => {}} />);
    const link = await screen.findByRole("link", { name: "Review memo" });
    expect(link.href).toContain("/phase7-5-review/");
    expect(link.href).toContain(`job_id=${job.id}`);
  });

  it("shows both private download actions for a complete job", async () => {
    const job = { ...base, status: "complete" };
    render(<ConversionProgress client={clientFor(job)} user={user} initialJob={job} onBack={() => {}} />);
    expect(await screen.findByRole("button", { name: "Download Word" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeInTheDocument();
  });

  it("offers the supported retry action for failed_retryable", async () => {
    const job = { ...base, status: "failed_retryable", stage: "worker_failed", error_code: "WORKER_INTERNAL_ERROR" };
    const client = clientFor(job);
    render(<ConversionProgress client={client} user={user} initialJob={job} onBack={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry conversion" }));
    await waitFor(() => expect(client.functions.invoke).toHaveBeenCalledWith("dispatch-memo", {
      body: { job_id: job.id },
    }));
  });

  it("offers retry when an initial workflow dispatch was restored to queued", async () => {
    const job = { ...base, status: "queued", stage: "dispatch_retry", error_code: "GITHUB_DISPATCH_FAILED" };
    render(<ConversionProgress client={clientFor(job)} user={user} initialJob={job} onBack={() => {}} />);
    expect(await screen.findByRole("button", { name: "Retry conversion" })).toBeInTheDocument();
    expect(screen.getByText("Needs retry")).toBeInTheDocument();
  });

  it("shows a terminal message without a retry action for failed", async () => {
    const job = { ...base, status: "failed", stage: "worker_failed", error_code: "TERMINAL" };
    render(<ConversionProgress client={clientFor(job)} user={user} initialJob={job} onBack={() => {}} />);
    expect(await screen.findByRole("heading", { name: "This conversion could not finish" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry conversion" })).not.toBeInTheDocument();
  });
});
