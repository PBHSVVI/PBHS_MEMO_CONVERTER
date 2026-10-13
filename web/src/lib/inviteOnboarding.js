export const INVITE_EXPIRED_MESSAGE =
  "That account setup link is no longer used. Open the PBHS Mathematics account setup page and request a new code.";

export function passwordChecks(password) {
  return {
    length: password.length >= 8,
    lowercase: /[a-z]/.test(password),
    uppercase: /[A-Z]/.test(password),
    digit: /\d/.test(password),
    symbol: /[^A-Za-z0-9]/.test(password),
  };
}

export function passwordIsStrong(password) {
  return Object.values(passwordChecks(password)).every(Boolean);
}

export function inviteRouteState(href = window.location.href) {
  const url = new URL(href);
  const query = url.searchParams;
  const hash = new URLSearchParams(url.hash.replace(/^#/, ""));
  const errorCode = query.get("error_code") || hash.get("error_code") || query.get("error") || hash.get("error");
  const description = query.get("error_description") || hash.get("error_description") || "";
  const expired = /expired|otp_expired/i.test(`${errorCode || ""} ${description}`);
  const onboarding = query.get("onboarding");
  const active = onboarding === "setup" || onboarding === "invite" || query.get("type") === "invite" || hash.get("type") === "invite";
  return { active: active || expired, expired, errorCode: errorCode || null };
}

export function normalSignInUrl(href = window.location.href) {
  const url = new URL(href);
  url.search = "";
  url.hash = "";
  return url.toString();
}

export function safeInviteIdentity(user) {
  return {
    name: String(user?.app_metadata?.pbhs_display_name || "PBHS Mathematics staff member"),
    email: String(user?.email || ""),
  };
}
