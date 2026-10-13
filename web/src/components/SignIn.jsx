import { useState } from "react";
import { BrandCrest } from "./BrandIdentity";

export function SignIn({ client, setupComplete = false }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [state, setState] = useState({ busy: false, error: "" });

  async function submit(event) {
    event.preventDefault();
    setState({ busy: true, error: "" });
    const { error } = await client.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    setState({
      busy: false,
      error: error ? "Sign-in failed. Check your email and password, then try again." : "",
    });
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-identity">
          <BrandCrest context="signin" />
          <p className="school-name">Pretoria Boys High School</p>
          <p className="department-name">Mathematics Department</p>
          <h1>Memo Converter</h1>
        </div>
        <p className="lede">Turn a source memo into a checked, consistently formatted Word and PDF memo.</p>
        {setupComplete && <p className="notice success" role="status">{setupComplete === "password"
          ? <>Your password has been changed.<br />Please sign in again with your new password.</>
          : "Your PBHS Mathematics account is ready. Sign in with your email and new password."}</p>}
        <form onSubmit={submit}>
          <label>
            Email address
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {state.error && <p className="notice danger" role="alert">{state.error}</p>}
          <button className="button primary full" disabled={state.busy}>
            {state.busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="fine-print">Use your approved teacher account. Accounts are created by invitation only. Your uploaded memos remain private to your account.</p>
      </section>
    </main>
  );
}
