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
      signInWithOtp: vi.fn(async () => ({ error: null })),
      verifyOtp: vi.fn(),
      signOut: vi.fn(),
      updateUser: vi.fn(),
    },
    rpc: vi.fn(),
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

  it("routes an obsolete invite to the harmless code setup page", async () => {
    window.history.replaceState({}, "", "/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=invite&error_code=otp_expired");
    render(<App client={authClient(null)} />);
    expect(await screen.findByText(/now uses a code/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Set up my account" }));
    expect(await screen.findByRole("heading", { name: "Create your PBHS Mathematics account" })).toBeInTheDocument();
    window.history.replaceState({}, "", "/");
  });

  it("scanner GETs of the setup page do not consume or modify an account", async () => {
    window.history.replaceState({}, "", "/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=setup");
    const first = authClient(null);
    const view = render(<App client={first} />);
    expect(await screen.findByRole("heading", { name: "Create your PBHS Mathematics account" })).toBeInTheDocument();
    expect(first.auth.signInWithOtp).not.toHaveBeenCalled();
    expect(first.auth.verifyOtp).not.toHaveBeenCalled();
    expect(first.auth.updateUser).not.toHaveBeenCalled();
    expect(first.auth.signOut).not.toHaveBeenCalled();
    view.unmount();

    const second = authClient(null);
    render(<App client={second} />);
    expect(await screen.findByRole("heading", { name: "Create your PBHS Mathematics account" })).toBeInTheDocument();
    expect(second.auth.signInWithOtp).not.toHaveBeenCalled();
    expect(second.auth.verifyOtp).not.toHaveBeenCalled();
    expect(second.auth.updateUser).not.toHaveBeenCalled();
    expect(second.auth.signOut).not.toHaveBeenCalled();
    window.history.replaceState({}, "", "/");
  });
});
