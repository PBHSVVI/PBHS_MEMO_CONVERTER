import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DepartmentDetails } from "./DepartmentDetails";

function complete() {
  fireEvent.change(screen.getByLabelText(/^Assessment type/), { target: { value: "class_test" } });
  fireEvent.change(screen.getByLabelText(/^Term/), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText(/^Assessment number/), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Time allocation value"), { target: { value: "45" } });
}

describe("editable generated document name", () => {
  it("keeps a manual edit across metadata changes and resets on request", () => {
    render(<DepartmentDetails initialContext={{ department: "mathematics", form: 4 }} onChange={vi.fn()} />);
    complete();
    const name = screen.getByLabelText(/Document name/);
    expect(name).toHaveValue("Form 4 Class Test 2 Term 4 2026");
    fireEvent.change(name, { target: { value: "Custom departmental title" } });
    fireEvent.change(screen.getByLabelText(/^Term/), { target: { value: "3" } });
    expect(name).toHaveValue("Custom departmental title");
    fireEvent.click(screen.getByRole("button", { name: "Reset to suggested name" }));
    expect(name).toHaveValue("Form 4 Class Test 2 Term 3 2026");
  });
});

