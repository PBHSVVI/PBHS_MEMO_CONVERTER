import { useMemo, useState } from "react";
import { BrandCrest } from "./BrandIdentity";
import {
  INVITE_EXPIRED_MESSAGE,
  passwordChecks,
  passwordIsStrong,
  safeInviteIdentity,
} from "../lib/inviteOnboarding";

const requirementLabels = {
  length: "At least 12 characters",
  lowercase: "A lowercase letter",
  uppercase: "An uppercase letter",
  digit: "A number",
  symbol: "A symbol",
};

export function InviteOnboarding({ client, session, onComplete }) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [state, setState] = useState({ busy: false, error: "" });
  const checks = useMemo(() => passwordChecks(password), [password]);
  const identity = safeInviteIdentity(session?.user);

  async function submit(event) {
    event.preventDefault();
    if (!passwordIsStrong(password)) {
      setState({ busy: false, error: "Your password does not yet meet every requirement." });
      return;
    }
    if (password !== confirmation) {
      setState({ busy: false, error: "The two passwords do not match." });
      return;
    }
    setState({ busy: true, error: "" });
    const { error } = await client.auth.updateUser({ password });
    if (error) {
      setState({ busy: false, error: "We could not finish account setup. Ask the Mathematics Department administrator for a new invitation." });
      return;
    }
    await client.auth.signOut();
    onComplete(identity.email);
  }

  return (
    <main className="auth-shell">
      <section className="auth-card onboarding-card">
        <div className="auth-identity auth-identity--compact">
          <BrandCrest context="signin" />
          <p className="school-name">Pretoria Boys High School</p>
          <p className="department-name">Mathematics Department</p>
        </div>
        <h1>Set up your PBHS Mathematics account</h1>
        <div className="invite-identity" aria-label="Invited staff identity">
          <strong>{identity.name}</strong>
          <span>{identity.email}</span>
        </div>
        <p className="lede">Choose a strong private password that you do not use for another account.</p>
        <form onSubmit={submit}>
          <label>Create password<input type="password" autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <ul className="password-requirements" aria-label="Password requirements">
            {Object.entries(requirementLabels).map(([key, label]) => <li className={checks[key] ? "met" : ""} key={key}>{label}</li>)}
          </ul>
          <label>Confirm password<input type="password" autoComplete="new-password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          {state.error && <p className="notice danger" role="alert">{state.error}</p>}
          <button className="button primary full" disabled={state.busy}>{state.busy ? "Creating account…" : "Create my account"}</button>
        </form>
        <p className="fine-print">A password manager is recommended. Compromised-password checking is not available on the current service plan.</p>
      </section>
    </main>
  );
}

export function ExpiredInvitation({ onSignIn }) {
  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-identity auth-identity--compact">
          <BrandCrest context="signin" />
          <p className="school-name">Pretoria Boys High School</p>
          <p className="department-name">Mathematics Department</p>
        </div>
        <h1>Invitation unavailable</h1>
        <p className="notice danger" role="alert">{INVITE_EXPIRED_MESSAGE}</p>
        <button className="button primary full" onClick={onSignIn}>Return to sign in</button>
      </section>
    </main>
  );
}
