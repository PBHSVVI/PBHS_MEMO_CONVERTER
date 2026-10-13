import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

function authClient(session) {
  const unsubscribe = vi.fn();
  return {
    auth: {
      getSession: vi.fn(async () => ({ data: { session } })),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe } } })),
      signInWithPassword: vi.fn(),
      signOut: vi.fn(),
      updateUser: vi.fn(),
    },
    from: vi.fn(() => ({
      select: () => ({
        order: () => ({
          limit: async () => ({ data: [], error: null }),
        }),
      }),
    })),
  };
}

describe("auth state routing", () => {
  it("shows sign in when there is no authenticated session", async () => {
    render(<App client={authClient(null)} />);
    expect(await screen.findByRole("heading", { name: "Memo Converter" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Pretoria Boys High School 125th anniversary crest" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign up|create account/i })).not.toBeInTheDocument();
  });

  it("opens the teacher dashboard for an authenticated session", async () => {
    const client = authClient({ user: { id: "7699652c-9795-40e6-a730-ac38c18f5a86", email: "teacher@pbhs.example" } });
    render(<App client={client} />);
    expect(await screen.findByRole("heading", { name: "Mathematics papers" })).toBeInTheDocument();
    await waitFor(() => expect(client.from).toHaveBeenCalledWith("jobs"));
    expect(client.from).toHaveBeenCalledWith("paper_library_summary");
    expect(screen.getByText("teacher@pbhs.example")).toBeInTheDocument();
  });

  it("routes an expired invite to a safe reissue message", async () => {
    window.history.replaceState({}, "", "/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=invite&error_code=otp_expired");
    render(<App client={authClient(null)} />);
    expect(await screen.findByText(/This invitation has expired/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Return to sign in" })).toBeInTheDocument();
    window.history.replaceState({}, "", "/");
  });

  it("finishes invite setup at the normal sign-in screen", async () => {
    window.history.replaceState({}, "", "/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=invite");
    const client = authClient({ user: { id: "7699652c-9795-40e6-a730-ac38c18f5a86", email: "teacher@pbhs.example", app_metadata: { pbhs_display_name: "Teacher Example" } } });
    client.auth.updateUser.mockResolvedValue({ error: null });
    client.auth.signOut.mockResolvedValue({ error: null });
    render(<App client={client} />);
    fireEvent.change(await screen.findByLabelText("Create password"), { target: { value: "StrongPassword9!" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "StrongPassword9!" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my account" }));
    expect(await screen.findByRole("status")).toHaveTextContent("account is ready");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(client.auth.signOut).toHaveBeenCalledTimes(1);
    window.history.replaceState({}, "", "/");
  });
});
