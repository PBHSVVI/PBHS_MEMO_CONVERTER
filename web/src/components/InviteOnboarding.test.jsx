import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExpiredInvitation, InviteOnboarding } from "./InviteOnboarding";
import { INVITE_EXPIRED_MESSAGE } from "../lib/inviteOnboarding";

function client(updateError = null) {
  return { auth: { updateUser: vi.fn(async () => ({ error: updateError })), signOut: vi.fn(async () => ({})) } };
}

const session = { user: { email: "synthetic@example.invalid", app_metadata: { pbhs_display_name: "Synthetic Teacher" }, user_metadata: { role: "hod" } } };

describe("invite onboarding", () => {
  it("shows safe identity and clear password requirements", () => {
    render(<InviteOnboarding client={client()} session={session} onComplete={() => {}} />);
    expect(screen.getByRole("heading", { name: "Set up your PBHS Mathematics account" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic Teacher")).toBeInTheDocument();
    expect(screen.getByText("synthetic@example.invalid")).toBeInTheDocument();
    expect(screen.getByText("At least 12 characters")).toBeInTheDocument();
    expect(screen.queryByText("hod")).not.toBeInTheDocument();
  });

  it("rejects weak and mismatched passwords before Auth", async () => {
    const auth = client();
    render(<InviteOnboarding client={auth} session={session} onComplete={() => {}} />);
    const fields = screen.getAllByLabelText(/password/i);
    fireEvent.change(fields[0], { target: { value: "weak" } });
    fireEvent.change(fields[1], { target: { value: "weak" } });
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("does not yet meet");
    expect(auth.auth.updateUser).not.toHaveBeenCalled();
  });

  it("sets the password, signs the invite session out, and completes", async () => {
    const auth = client(); const complete = vi.fn();
    render(<InviteOnboarding client={auth} session={session} onComplete={complete} />);
    const fields = screen.getAllByLabelText(/password/i);
    fireEvent.change(fields[0], { target: { value: "StrongPassword9!" } });
    fireEvent.change(fields[1], { target: { value: "StrongPassword9!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));
    await waitFor(() => expect(auth.auth.updateUser).toHaveBeenCalledWith({ password: "StrongPassword9!" }));
    expect(auth.auth.signOut).toHaveBeenCalledTimes(1);
    expect(complete).toHaveBeenCalledWith("synthetic@example.invalid");
  });

  it("uses the explicit expired-invitation message", () => {
    render(<ExpiredInvitation onSignIn={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent(INVITE_EXPIRED_MESSAGE);
  });
});
