import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SupportIncident } from "./SupportIncident";
import { submitSupportIncident } from "../lib/supportIncidents";

vi.mock("../lib/supportIncidents", async () => {
  const original = await vi.importActual("../lib/supportIncidents");
  return { ...original, submitSupportIncident: vi.fn(async () => ({ reference: "PBHS-20261013-AB12", notification_delayed: true })) };
});

describe("SupportIncident", () => {
  it("saves without navigating or disturbing the current screen", async () => {
    const before = window.location.href;
    render(<div><span>Current review work</span><SupportIncident client={{}} user={{ id: "teacher-1" }} context={{ currentView: "review" }} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Help / Report a problem" }));
    expect(screen.getByRole("heading", { name: "What happened?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByText("Your report has been saved.")).toBeInTheDocument();
    expect(screen.getByText(/PBHS-20261013-AB12/)).toBeInTheDocument();
    expect(screen.getByText(/Automatic notification is delayed/)).toBeInTheDocument();
    expect(screen.getByText("Current review work")).toBeInTheDocument();
    await waitFor(() => expect(window.location.href).toBe(before));
  });

  it("shows a safe fallback when the incident cannot be saved", async () => {
    submitSupportIncident.mockRejectedValueOnce({ fallbackReference: "JOB-A284E625" });
    render(<SupportIncident client={{}} user={{ id: "teacher-1" }} context={{ currentView: "processing" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Help / Report a problem" }));
    fireEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByText("We couldn't send the report.")).toBeInTheDocument();
    expect(screen.getByText(/JOB-A284E625/)).toBeInTheDocument();
    expect(screen.queryByText("Your report has been saved.")).not.toBeInTheDocument();
  });
});
