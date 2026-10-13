import { useMemo, useState } from "react";
import { BrandCrest } from "./BrandIdentity";
import { passwordChecks, passwordIsStrong } from "../lib/inviteOnboarding";
import { completeFirstLogin } from "../lib/firstLogin";

const requirements = {
  length: "At least 8 characters",
  lowercase: "A lowercase letter",
  uppercase: "An uppercase letter",
  digit: "A number",
  symbol: "A symbol",
};

export function MandatoryPasswordChange({ client, email, onComplete }) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [state, setState] = useState({ busy: false, error: "" });
  const checks = useMemo(() => passwordChecks(password), [password]);

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
    const { data, error } = await completeFirstLogin(client, password);
    if (error || data?.ok !== true) {
      setState({ busy: false, error: "We could not change your password. Please try again or contact the Mathematics Department administrator." });
      return;
    }
    // The backend has revoked Auth sessions. Always clear this browser's local
    // session as well before returning to the normal sign-in screen.
    await client.auth.signOut({ scope: "local" });
    onComplete();
  }

  return (
    <main className="auth-shell">
      <section className="auth-card onboarding-card">
        <div className="auth-identity auth-identity--compact">
          <BrandCrest context="signin" />
          <p className="school-name">Pretoria Boys High School</p>
          <p className="department-name">Mathematics Department</p>
        </div>
        <h1>Choose your private password</h1>
        <p className="lede">Your staff code was a temporary first-login password. Replace it before opening the Teacher App.</p>
        <div className="invite-identity" aria-label="Signed-in staff identity"><span>{email}</span></div>
        <form onSubmit={submit}>
          <label>New password<input type="password" autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <ul className="password-requirements" aria-label="Password requirements">
            {Object.entries(requirements).map(([key, label]) => <li className={checks[key] ? "met" : ""} key={key}>{label}</li>)}
          </ul>
          <label>Confirm password<input type="password" autoComplete="new-password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          {state.error && <p className="notice danger" role="alert">{state.error}</p>}
          <button className="button primary full" disabled={state.busy}>{state.busy ? "Setting password…" : "Set my password"}</button>
        </form>
      </section>
    </main>
  );
}
