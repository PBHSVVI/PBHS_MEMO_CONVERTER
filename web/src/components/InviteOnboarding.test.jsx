import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExpiredInvitation, InviteOnboarding } from "./InviteOnboarding";
import { SETUP_PROFILE_MESSAGE } from "../lib/otpOnboarding";

const session = {
  access_token: "test-access-token",
  user: { email: "synthetic@example.invalid", app_metadata: { pbhs_display_name: "Synthetic Teacher" } },
};

function client(overrides = {}) {
  const { auth: authOverrides = {}, ...clientOverrides } = overrides;
  return {
    auth: {
      signInWithOtp: vi.fn(async () => ({ error: null })),
      verifyOtp: vi.fn(async () => ({ data: { session }, error: null })),
      updateUser: vi.fn(async () => ({ error: null })),
      signOut: vi.fn(async () => ({ error: null })),
      ...authOverrides,
    },
    rpc: vi.fn(async () => ({ data: true, error: null })),
    ...clientOverrides,
  };
}

async function requestAndVerify(auth, code = "123456") {
  fireEvent.change(screen.getByLabelText("PBHS email address"), { target: { value: " Synthetic@Example.Invalid " } });
  fireEvent.click(screen.getByRole("button", { name: "Send setup code" }));
  expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Setup code"), { target: { value: code } });
  fireEvent.click(screen.getByRole("button", { name: "Verify code" }));
  await waitFor(() => expect(auth.auth.verifyOtp).toHaveBeenCalled());
}

describe("scanner-safe code onboarding", () => {
  it("requests a code without allowing Auth to create a user", async () => {
    const auth = client();
    render(<InviteOnboarding client={auth} onComplete={() => {}} />);
    fireEvent.change(screen.getByLabelText("PBHS email address"), { target: { value: " Synthetic@Example.Invalid " } });
    fireEvent.click(screen.getByRole("button", { name: "Send setup code" }));
    await waitFor(() => expect(auth.auth.signInWithOtp).toHaveBeenCalledWith({
      email: "synthetic@example.invalid",
      options: { shouldCreateUser: false },
    }));
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  });

  it("verifies the numeric code, checks the active profile, sets a strong password, and forces sign-out", async () => {
    const auth = client();
    const complete = vi.fn();
    render(<InviteOnboarding client={auth} onComplete={complete} />);
    await requestAndVerify(auth, "123 456");
    expect(auth.auth.verifyOtp).toHaveBeenCalledWith({
      email: "synthetic@example.invalid",
      token: "123456",
      type: "email",
    });
    expect(auth.rpc).toHaveBeenCalledWith("pbhs_active_profile_status");
    expect(await screen.findByRole("heading", { name: "Choose your password" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic Teacher")).toBeInTheDocument();
    const fields = screen.getAllByLabelText(/password/i);
    fireEvent.change(fields[0], { target: { value: "StrongPassword9!" } });
    fireEvent.change(fields[1], { target: { value: "StrongPassword9!" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my account" }));
    await waitFor(() => expect(auth.auth.updateUser).toHaveBeenCalledWith({ password: "StrongPassword9!" }));
    expect(auth.auth.signOut).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("status")).toHaveTextContent("account is ready");
    fireEvent.click(screen.getByRole("button", { name: "Go to Sign In" }));
    expect(complete).toHaveBeenCalledWith("synthetic@example.invalid");
  });

  it("rejects weak and mismatched passwords before Auth", async () => {
    const auth = client();
    render(<InviteOnboarding client={auth} onComplete={() => {}} />);
    await requestAndVerify(auth);
    const fields = await screen.findAllByLabelText(/password/i);
    fireEvent.change(fields[0], { target: { value: "weak" } });
    fireEvent.change(fields[1], { target: { value: "weak" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("does not yet meet");
    expect(auth.auth.updateUser).not.toHaveBeenCalled();
  });

  it("fails an invalid or replayed code without reaching profile or password setup", async () => {
    const auth = client({ auth: { verifyOtp: vi.fn(async () => ({ data: {}, error: new Error("otp_expired") })) } });
    render(<InviteOnboarding client={auth} onComplete={() => {}} />);
    await requestAndVerify(auth, "000000");
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or has expired");
    expect(auth.rpc).not.toHaveBeenCalled();
    expect(auth.auth.updateUser).not.toHaveBeenCalled();
  });

  it.each([
    ["missing", { data: false, error: null }],
    ["inactive", { data: false, error: null }],
    ["unavailable", { data: null, error: new Error("unavailable") }],
  ])("denies a %s profile after OTP verification", async (_label, profileResult) => {
    const auth = client({ rpc: vi.fn(async () => profileResult) });
    render(<InviteOnboarding client={auth} onComplete={() => {}} />);
    await requestAndVerify(auth);
    expect(await screen.findByRole("alert")).toHaveTextContent(SETUP_PROFILE_MESSAGE);
    expect(auth.auth.signOut).toHaveBeenCalledTimes(1);
    expect(auth.auth.updateUser).not.toHaveBeenCalled();
  });

  it("does not advance an unprovisioned address when Auth rejects the request", async () => {
    const auth = client({ auth: { signInWithOtp: vi.fn(async () => ({ error: new Error("user not found") })) } });
    render(<InviteOnboarding client={auth} onComplete={() => {}} />);
    fireEvent.change(screen.getByLabelText("PBHS email address"), { target: { value: "unknown@example.invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "Send setup code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not send");
    expect(screen.getByRole("heading", { name: "Create your PBHS Mathematics account" })).toBeInTheDocument();
    expect(auth.auth.verifyOtp).not.toHaveBeenCalled();
  });

  it("reissues through the same bounded OTP request", async () => {
    const auth = client();
    render(<InviteOnboarding client={auth} onComplete={() => {}} />);
    fireEvent.change(screen.getByLabelText("PBHS email address"), { target: { value: "synthetic@example.invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "Send setup code" }));
    fireEvent.click(await screen.findByRole("button", { name: "Send a new code" }));
    await waitFor(() => expect(auth.auth.signInWithOtp).toHaveBeenCalledTimes(2));
    expect(auth.auth.signInWithOtp.mock.calls[1][0].options.shouldCreateUser).toBe(false);
  });

  it("converts an obsolete invite error into the code setup route", () => {
    const open = vi.fn();
    render(<ExpiredInvitation onSetup={open} />);
    fireEvent.click(screen.getByRole("button", { name: "Set up my account" }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/token|Supabase|RLS/i)).not.toBeInTheDocument();
  });
});
