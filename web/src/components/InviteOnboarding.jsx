import { useMemo, useState } from "react";
import { BrandCrest } from "./BrandIdentity";
import { passwordChecks, passwordIsStrong, safeInviteIdentity } from "../lib/inviteOnboarding";
import {
  activeSetupProfile,
  normalizeSetupEmail,
  requestSetupCode,
  SETUP_PROFILE_MESSAGE,
  verifySetupCode,
} from "../lib/otpOnboarding";

const requirementLabels = {
  length: "At least 8 characters",
  lowercase: "A lowercase letter",
  uppercase: "An uppercase letter",
  digit: "A number",
  symbol: "A symbol",
};

function Shell({ children }) {
  return (
    <main className="auth-shell">
      <section className="auth-card onboarding-card">
        <div className="auth-identity auth-identity--compact">
          <BrandCrest context="signin" />
          <p className="school-name">Pretoria Boys High School</p>
          <p className="department-name">Mathematics Department</p>
        </div>
        {children}
      </section>
    </main>
  );
}

export function InviteOnboarding({ client, onComplete }) {
  const [step, setStep] = useState("email");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [session, setSession] = useState(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [state, setState] = useState({ busy: false, error: "" });
  const checks = useMemo(() => passwordChecks(password), [password]);

  async function sendCode(event) {
    event?.preventDefault();
    const normalized = normalizeSetupEmail(email);
    if (!normalized) return;
    setState({ busy: true, error: "" });
    const { error } = await requestSetupCode(client, normalized);
    if (error) {
      setState({ busy: false, error: "We could not send a setup code. Check the email address or contact the Mathematics Department administrator." });
      return;
    }
    setEmail(normalized);
    setToken("");
    setStep("otp");
    setState({ busy: false, error: "" });
  }

  async function verifyCode(event) {
    event.preventDefault();
    setState({ busy: true, error: "" });
    const { data, error } = await verifySetupCode(client, email, token);
    if (error || !data?.session) {
      setState({ busy: false, error: "That setup code is invalid or has expired. Request a new code and try again." });
      return;
    }
    const profile = await activeSetupProfile(client);
    if (!profile.active) {
      await client.auth.signOut();
      setSession(null);
      setState({ busy: false, error: SETUP_PROFILE_MESSAGE });
      return;
    }
    setSession(data.session);
    setStep("password");
    setState({ busy: false, error: "" });
  }

  async function createPassword(event) {
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
      setState({ busy: false, error: "We could not finish account setup. Request a new setup code and try again." });
      return;
    }
    await client.auth.signOut();
    setStep("success");
    setState({ busy: false, error: "" });
  }

  if (step === "email") {
    return (
      <Shell>
        <h1>Create your PBHS Mathematics account</h1>
        <p className="lede">We'll send a one-time setup code to your PBHS email address.</p>
        <form onSubmit={sendCode}>
          <label>PBHS email address<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          {state.error && <p className="notice danger" role="alert">{state.error}</p>}
          <button className="button primary full" disabled={state.busy}>{state.busy ? "Sending code…" : "Send setup code"}</button>
        </form>
      </Shell>
    );
  }

  if (step === "otp") {
    return (
      <Shell>
        <h1>Check your email</h1>
        <p className="lede">We sent a one-time setup code to your PBHS email address.</p>
        <div className="invite-identity"><span>{email}</span></div>
        <form onSubmit={verifyCode}>
          <label>Setup code<input className="setup-code" inputMode="numeric" autoComplete="one-time-code" required value={token} onChange={(event) => setToken(event.target.value)} /></label>
          {state.error && <p className="notice danger" role="alert">{state.error}</p>}
          <button className="button primary full" disabled={state.busy}>{state.busy ? "Verifying…" : "Verify code"}</button>
          <button className="button quiet full setup-resend" type="button" disabled={state.busy} onClick={sendCode}>Send a new code</button>
        </form>
      </Shell>
    );
  }

  if (step === "success") {
    return (
      <Shell>
        <h1>Your account is ready</h1>
        <p className="notice success" role="status">Your PBHS Mathematics account is ready.</p>
        <button className="button primary full" onClick={() => onComplete(email)}>Go to Sign In</button>
      </Shell>
    );
  }

  const identity = safeInviteIdentity(session?.user);
  return (
    <Shell>
      <h1>Choose your password</h1>
      <div className="invite-identity" aria-label="Verified staff identity"><strong>{identity.name}</strong><span>{identity.email}</span></div>
      <form onSubmit={createPassword}>
        <label>Password<input type="password" autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <ul className="password-requirements" aria-label="Password requirements">
          {Object.entries(requirementLabels).map(([key, label]) => <li className={checks[key] ? "met" : ""} key={key}>{label}</li>)}
        </ul>
        <label>Confirm password<input type="password" autoComplete="new-password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
        {state.error && <p className="notice danger" role="alert">{state.error}</p>}
        <button className="button primary full" disabled={state.busy}>{state.busy ? "Creating account…" : "Create my account"}</button>
      </form>
      <p className="fine-print">A password manager is recommended. Compromised-password checking is not available on the current service plan.</p>
    </Shell>
  );
}

export function ExpiredInvitation({ onSetup }) {
  return (
    <Shell>
      <h1>Use a setup code</h1>
      <p className="notice info">For your security, PBHS Mathematics now uses a code sent to your email instead of a one-time link.</p>
      <button className="button primary full" onClick={onSetup}>Set up my account</button>
    </Shell>
  );
}
