import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UploadMemo } from "./UploadMemo";
import { createAndDispatchJob } from "../lib/memoService";

vi.mock("../lib/memoService", () => ({ createAndDispatchJob: vi.fn() }));

const props = () => ({ client: {}, user: { id: "teacher" }, onBack: vi.fn(), onCreated: vi.fn() });
const memo = (name = "memo.pdf", type = "application/pdf") => new File(["memo"], name, { type });
const zone = () => screen.getByText(/Choose or drop a memo file|Choose a different file|Drop one memo here/).closest("label");

function completeDetails(type = "Class Test") {
  fireEvent.change(screen.getByLabelText(/^Subject/), { target: { value: "mathematics" } });
  fireEvent.change(screen.getByLabelText(/^Form/), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText(/^Assessment type/), { target: { value: type.toLowerCase().replaceAll(" ", "_") } });
  fireEvent.change(screen.getByLabelText(/^Term/), { target: { value: "4" } });
  if (type === "Class Test") fireEvent.change(screen.getByLabelText(/^Assessment number/), { target: { value: "2" } });
  if (type === "Examination") fireEvent.change(screen.getByLabelText(/^Paper/), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Time allocation value"), { target: { value: "45" } });
}

describe("required memo upload", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the upload gate closed until file and all filing details are valid", () => {
    render(<UploadMemo {...props()} />);
    const button = screen.getByRole("button", { name: "Upload and convert" });
    expect(screen.getByText("Department details")).toBeVisible();
    expect(button).toBeDisabled();
    fireEvent.drop(zone(), { dataTransfer: { files: [memo()] } });
    expect(button).toBeDisabled();
    completeDetails();
    expect(button).toBeEnabled();
  });

  it("creates no job/upload/dispatch when an incomplete form is submitted mechanically", () => {
    const { container } = render(<UploadMemo {...props()} />);
    fireEvent.drop(zone(), { dataTransfer: { files: [memo()] } });
    fireEvent.submit(container.querySelector("form"));
    expect(screen.getByRole("alert")).toHaveTextContent("complete the highlighted department details");
    expect(createAndDispatchJob).not.toHaveBeenCalled();
  });

  it("submits filing metadata and a generated name without teacher metadata", async () => {
    createAndDispatchJob.mockResolvedValue({ id: "job" });
    render(<UploadMemo {...props()} initialContext={{ department: "mathematics", form: 4 }} />);
    fireEvent.drop(zone(), { dataTransfer: { files: [memo()] } });
    fireEvent.change(screen.getByLabelText(/^Assessment type/), { target: { value: "class_test" } });
    fireEvent.change(screen.getByLabelText(/^Term/), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/^Assessment number/), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Time allocation value"), { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and convert" }));
    await waitFor(() => expect(createAndDispatchJob).toHaveBeenCalledTimes(1));
    const call = createAndDispatchJob.mock.calls[0][0];
    expect(call.displayName).toBe("Form 4 Class Test 2 Term 4 2026");
    expect(call.filingMetadata).toMatchObject({
      subject_scope: "mathematics", form: 4, assessment_type: "class_test", term: 4, year: 2026,
      assessment_number: { applicability: "required", value: 2 },
      paper: { applicability: "not_applicable", value: null },
      duration: { value: 45, unit: "minutes", duration_minutes: 45 },
    });
    expect(call).not.toHaveProperty("teacherMetadata");
  });

  it("prepopulates dashboard subject/form but permits changing them", () => {
    render(<UploadMemo {...props()} initialContext={{ department: "mathematics", form: 4 }} />);
    expect(screen.getByLabelText(/^Subject/)).toHaveValue("mathematics");
    expect(screen.getByLabelText(/^Form/)).toHaveValue("4");
    fireEvent.change(screen.getByLabelText(/^Form/), { target: { value: "5" } });
    expect(screen.getByLabelText(/^Form/)).toHaveValue("5");
  });

  it("rejects invalid and multiple dropped files", () => {
    render(<UploadMemo {...props()} />);
    fireEvent.drop(zone(), { dataTransfer: { files: [memo("notes.txt", "text/plain")] } });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a PDF, Word DOCX, PNG, or JPEG memo.");
    fireEvent.drop(zone(), { dataTransfer: { files: [memo(), memo("other.pdf")] } });
    expect(screen.getByRole("alert")).toHaveTextContent("Drop exactly one memo file at a time.");
  });

  it("prevents duplicate job creation", async () => {
    createAndDispatchJob.mockImplementation(() => new Promise(() => {}));
    render(<UploadMemo {...props()} />);
    fireEvent.drop(zone(), { dataTransfer: { files: [memo()] } });
    completeDetails();
    const button = screen.getByRole("button", { name: "Upload and convert" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(createAndDispatchJob).toHaveBeenCalledTimes(1));
  });
});
