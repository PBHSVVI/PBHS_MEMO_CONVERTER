import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MandatoryPasswordChange } from "./MandatoryPasswordChange";

function client(result = { data: { ok: true }, error: null }) {
  return {
    functions: { invoke: vi.fn(async () => result) },
    auth: { signOut: vi.fn(async () => ({ error: null })) },
  };
}

describe("mandatory first-login password change", () => {
  it("rejects a weak replacement without invoking the backend", async () => {
    const api = client();
    render(<MandatoryPasswordChange client={api} email="synthetic@example.invalid" onComplete={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "weak" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "weak" } });
    fireEvent.click(screen.getByRole("button", { name: "Set my password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not yet meet/);
    expect(api.functions.invoke).not.toHaveBeenCalled();
  });

  it("uses the narrow backend completion path, signs out, and returns to sign-in", async () => {
    const api = client();
    const onComplete = vi.fn();
    render(<MandatoryPasswordChange client={api} email="synthetic@example.invalid" onComplete={onComplete} />);
    const replacement = "PrivatePass!2468";
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: replacement } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: replacement } });
    fireEvent.click(screen.getByRole("button", { name: "Set my password" }));
    await waitFor(() => expect(api.functions.invoke).toHaveBeenCalledWith("complete-first-login", { body: { password: replacement } }));
    expect(api.auth.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(onComplete).toHaveBeenCalled();
  });

  it("stays gated when backend completion fails", async () => {
    const api = client({ data: null, error: new Error("denied") });
    render(<MandatoryPasswordChange client={api} email="synthetic@example.invalid" onComplete={vi.fn()} />);
    const replacement = "PrivatePass!2468";
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: replacement } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: replacement } });
    fireEvent.click(screen.getByRole("button", { name: "Set my password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not change/);
    expect(api.auth.signOut).not.toHaveBeenCalled();
  });
});
