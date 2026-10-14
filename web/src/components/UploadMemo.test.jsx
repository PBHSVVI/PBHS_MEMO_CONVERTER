import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UploadMemo } from "./UploadMemo";
import { createAndDispatchJob } from "../lib/memoService";

vi.mock("../lib/memoService", () => ({ createAndDispatchJob: vi.fn() }));

const props = () => ({
  client: {},
  user: { id: "teacher" },
  onBack: vi.fn(),
  onCreated: vi.fn(),
});
const memo = (name = "memo.pdf", type = "application/pdf") => new File(["memo"], name, { type });
const zone = () => screen.getByText(/Choose or drop a memo file|Choose a different file|Drop one memo here/).closest("label");

describe("memo upload drag and drop", () => {
  beforeEach(() => vi.clearAllMocks());

  it("accepts exactly one valid dropped file through normal validation", () => {
    render(<UploadMemo {...props()} />);
    const file = memo();
    fireEvent.dragEnter(zone(), { dataTransfer: { files: [file] } });
    expect(screen.getByText("Drop one memo here")).toBeInTheDocument();
    fireEvent.drop(zone(), { dataTransfer: { files: [file] } });
    expect(screen.getByText(/memo\.pdf/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload and convert" })).toBeEnabled();
  });

  it("rejects invalid and multiple dropped files", () => {
    render(<UploadMemo {...props()} />);
    fireEvent.drop(zone(), { dataTransfer: { files: [memo("notes.txt", "text/plain")] } });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a PDF, Word DOCX, PNG, or JPEG memo.");
    fireEvent.drop(zone(), { dataTransfer: { files: [memo(), memo("other.pdf")] } });
    expect(screen.getByRole("alert")).toHaveTextContent("Drop exactly one memo file at a time.");
  });

  it("ignores drops while an upload is busy", async () => {
    createAndDispatchJob.mockImplementation(() => new Promise(() => {}));
    render(<UploadMemo {...props()} />);
    fireEvent.drop(zone(), { dataTransfer: { files: [memo("first.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and convert" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled());
    fireEvent.drop(zone(), { dataTransfer: { files: [memo("second.pdf")] } });
    expect(createAndDispatchJob.mock.calls[0][0].file.name).toBe("first.pdf");
    expect(screen.getByText("Choose a different file")).toBeInTheDocument();
  });



  it("keeps document details optional and submits supplied values", async () => {
    createAndDispatchJob.mockResolvedValue({ id: "job" });
    render(<UploadMemo {...props()} />);
    expect(screen.getByText("Document details (optional)")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Document details (optional)"));
    fireEvent.change(screen.getByLabelText("Form / Grade"), { target: { value: "FORM 5" } });
    fireEvent.change(screen.getByLabelText("Time allocation value"), { target: { value: "3" } });
    fireEvent.drop(zone(), { dataTransfer: { files: [memo()] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and convert" }));
    await waitFor(() => expect(createAndDispatchJob).toHaveBeenCalledWith(
      expect.objectContaining({
        teacherMetadata: {
          schema_version: "1.0",
          values: { grade_label: "FORM 5", duration_minutes: 180 },
          confirmed_absent: [],
        },
      }),
    ));
  });

  it("uses a bounded Form selector instead of free text", () => {
    render(<UploadMemo {...props()} />);
    fireEvent.click(screen.getByText("Document details (optional)"));
    const field = screen.getByLabelText("Form / Grade");
    expect(field.tagName).toBe("SELECT");
    expect(Array.from(field.options).map((option) => option.value)).toEqual(["", "FORM 1", "FORM 2", "FORM 3", "FORM 4", "FORM 5"]);
  });

  it("blocks invalid year and duration before creating a job", async () => {
    render(<UploadMemo {...props()} />);
    fireEvent.click(screen.getByText("Document details (optional)"));
    fireEvent.change(screen.getByLabelText("Year"), { target: { value: "1999" } });
    fireEvent.change(screen.getByLabelText("Time allocation value"), { target: { value: "0" } });
    fireEvent.drop(zone(), { dataTransfer: { files: [memo()] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and convert" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please correct the highlighted document details");
    expect(createAndDispatchJob).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^Year/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Time allocation value")).toHaveAttribute("aria-invalid", "true");
  });

  it("submits blank optional fields and prevents duplicate job creation", async () => {
    createAndDispatchJob.mockImplementation(() => new Promise(() => {}));
    render(<UploadMemo {...props()} />);
    fireEvent.drop(zone(), { dataTransfer: { files: [memo()] } });
    const button = screen.getByRole("button", { name: "Upload and convert" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(createAndDispatchJob).toHaveBeenCalledTimes(1));
    expect(createAndDispatchJob.mock.calls[0][0].teacherMetadata).toEqual({ schema_version: "1.0", values: {}, confirmed_absent: [] });
  });

  it("prepopulates safe dashboard context without locking the fields", () => {
    render(<UploadMemo {...props()} initialContext={{ department: "mathematics", form: 4 }} />);
    fireEvent.click(screen.getByText("Document details (optional)"));
    expect(screen.getByLabelText("Subject")).toHaveValue("MATHEMATICS");
    expect(screen.getByLabelText("Form / Grade")).toHaveValue("FORM 4");
    fireEvent.change(screen.getByLabelText("Form / Grade"), { target: { value: "FORM 5" } });
    expect(screen.getByLabelText("Form / Grade")).toHaveValue("FORM 5");
  });

  it("preserves click-to-choose behavior", () => {
    const { container } = render(<UploadMemo {...props()} />);
    const file = memo("clicked.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } });
    expect(screen.getByText(/clicked\.docx/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload and convert" })).toBeEnabled();
  });
});
