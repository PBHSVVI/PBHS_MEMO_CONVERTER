import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DocumentDetails } from "./DocumentDetails";

describe("Document Details", () => {
  it("converts hours to duration minutes", async () => {
    const onSubmit = vi.fn();
    render(<DocumentDetails mode="review" missingFields={["duration_minutes"]} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Time allocation value"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply details" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      schema_version: "1.0",
      values: { duration_minutes: 180 },
      confirmed_absent: [],
    }));
  });

  it("submits explicit confirmed absence", async () => {
    const onSubmit = vi.fn();
    render(<DocumentDetails mode="review" missingFields={["grade_label", "duration_minutes"]} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "Leave blank" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      schema_version: "1.0",
      values: {},
      confirmed_absent: ["grade_label", "duration_minutes"],
    }));
  });

  it("shows source-derived fields read-only", () => {
    render(
      <DocumentDetails
        mode="review"
        missingFields={["grade_label"]}
        effectiveMetadata={{ paper: "PAPER 2" }}
        provenance={{ paper: { selected_provenance: "source", source_present: true } }}
      />,
    );
    expect(screen.getByText("PAPER 2")).toBeInTheDocument();
    expect(screen.getByText("From source")).toBeInTheDocument();
    expect(screen.queryByLabelText("Paper")).not.toBeInTheDocument();
  });

  it("shows completed details as read-only", () => {
    render(
      <DocumentDetails
        mode="readonly"
        effectiveMetadata={{ grade_label: "FORM 5", duration_minutes: 180 }}
        provenance={{ grade_label: { selected_provenance: "teacher" } }}
      />,
    );
    expect(screen.getByText("FORM 5")).toBeInTheDocument();
    expect(screen.getByText("Create a revised conversion to change document details.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
