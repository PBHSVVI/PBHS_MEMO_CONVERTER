import { render, screen, waitFor } from "@testing-library/react";
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
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("opens the teacher dashboard for an authenticated session", async () => {
    const client = authClient({ user: { id: "7699652c-9795-40e6-a730-ac38c18f5a86", email: "teacher@pbhs.example" } });
    render(<App client={client} />);
    expect(await screen.findByRole("heading", { name: "Convert a mathematics memo" })).toBeInTheDocument();
    await waitFor(() => expect(client.from).toHaveBeenCalledWith("jobs"));
    expect(screen.getByText("teacher@pbhs.example")).toBeInTheDocument();
  });
});
