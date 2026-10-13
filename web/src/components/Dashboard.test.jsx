import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "./Dashboard";
import { listDepartmentPapers, listRecentJobs } from "../lib/memoService";

vi.mock("../lib/memoService", () => ({ listDepartmentPapers: vi.fn(), listRecentJobs: vi.fn() }));

const user = { id: "teacher-1", email: "teacher@pbhs.example", app_metadata: { pbhs_display_name: "Teacher Example" } };
const ownerJob = {
  id: "owner-1", user_id: user.id, status: "processing", stage: "structure",
  source_filename: "source.docx", created_at: "2026-10-01T08:00:00Z", updated_at: "2026-10-01T09:00:00Z",
  teacher_metadata: { values: { subject: "MATHEMATICS", exam_type: "CONTROL TEST", paper: "PAPER 1", grade_label: "FORM 1", year: 2026 } },
};
const libraryRow = {
  job_id: "library-1", owner_user_id: "teacher-2", owner_display_name: "Other Teacher",
  subject_scope: "fs_mathematics", subject_display: "FS MATHEMATICS", assessment_type: "FINAL EXAMINATION",
  paper: "PAPER 2", grade_label: "FORM 5", year: 2026, workflow_bucket: "completed",
  status_source: "complete", stage_source: "complete", updated_at: "2026-10-02T09:00:00Z", source_filename: "raw.pdf",
};

function renderDashboard(overrides = {}) {
  return render(<Dashboard client={{}} user={{ ...user, ...overrides }} onConvert={vi.fn()} onOpen={vi.fn()} />);
}

describe("department workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    listRecentJobs.mockResolvedValue([ownerJob]);
    listDepartmentPapers.mockResolvedValue([libraryRow]);
  });

  it("replaces the old recent-conversions landing with the required hierarchy", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { name: "Mathematics papers" })).toBeInTheDocument();
    expect(screen.getByLabelText("Department")).toBeInTheDocument();
    expect(screen.getByLabelText("Work state")).toBeInTheDocument();
    expect(screen.getByLabelText("Paper ownership")).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Form" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recent conversions" })).not.toBeInTheDocument();
  });

  it("shows owner work through My papers and preserves metadata-first identity", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { name: "CONTROL TEST · PAPER 1" })).toBeInTheDocument();
    expect(screen.getByText("FORM 1 · 2026")).toBeInTheDocument();
    expect(screen.getByText("source.docx")).toBeInTheDocument();
  });

  it("filters All papers by department, completed state and one active form", async () => {
    renderDashboard();
    await screen.findByRole("heading", { name: "CONTROL TEST · PAPER 1" });
    fireEvent.click(within(screen.getByLabelText("Paper ownership")).getByRole("button", { name: "All papers" }));
    fireEvent.click(within(screen.getByLabelText("Department")).getByRole("button", { name: "FS Mathematics" }));
    fireEvent.click(within(screen.getByLabelText("Work state")).getByRole("button", { name: /Completed/ }));
    fireEvent.click(screen.getByRole("tab", { name: /Form 5/ }));
    expect(await screen.findByRole("heading", { name: "FINAL EXAMINATION · PAPER 2" })).toBeInTheDocument();
    expect(screen.getByText("Other Teacher")).toBeInTheDocument();
    expect(screen.getByText("Department paper")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "CONTROL TEST · PAPER 1" })).not.toBeInTheDocument();
  });

  it("shows an intentional filtered empty state", async () => {
    renderDashboard();
    await screen.findByRole("heading", { name: "CONTROL TEST · PAPER 1" });
    fireEvent.click(screen.getByRole("tab", { name: /Form 4/ }));
    expect(screen.getByRole("heading", { name: "No in-progress Form 4 Mathematics papers." })).toBeInTheDocument();
  });

  it("fails cleanly when the department library is unavailable", async () => {
    listDepartmentPapers.mockRejectedValue(new Error("permission denied"));
    renderDashboard({ app_metadata: {} });
    await waitFor(() => expect(listDepartmentPapers).toHaveBeenCalled());
    fireEvent.click(within(screen.getByLabelText("Paper ownership")).getByRole("button", { name: "All papers" }));
    expect(await screen.findByRole("heading", { name: "Your department library access has not been activated yet." })).toBeInTheDocument();
    expect(screen.queryByText(/permission denied|RLS|Supabase|department_profiles/i)).not.toBeInTheDocument();
  });
});
