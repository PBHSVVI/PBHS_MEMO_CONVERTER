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

  it("preserves click-to-choose behavior", () => {
    const { container } = render(<UploadMemo {...props()} />);
    const file = memo("clicked.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } });
    expect(screen.getByText(/clicked\.docx/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload and convert" })).toBeEnabled();
  });
});
