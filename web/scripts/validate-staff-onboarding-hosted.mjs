import { randomBytes } from "node:crypto";
import process from "node:process";
import { ProvisioningError, createSupabaseAdmin, provisionStaff, redactSensitiveValue, selectTrustedCredential } from "./staffProvisioning.mjs";

const projectRef = process.env.PBHS_VALIDATION_PROJECT_REF;
const url = process.env.SUPABASE_URL;
const publishable = process.env.SUPABASE_PUBLISHABLE_KEY;
if (projectRef !== "wgkydsildfmbqzvicuwm" || url !== `https://${projectRef}.supabase.co`) throw new Error("Hosted validation is locked to the Phase 8.3 validation project.");
if (!publishable?.startsWith("sb_publishable_")) throw new Error("SUPABASE_PUBLISHABLE_KEY must contain a modern Supabase publishable key.");
const credential = selectTrustedCredential({ SUPABASE_SECRET_KEY: process.env.SUPABASE_SECRET_KEY });
const secret = credential.secret;
const admin = createSupabaseAdmin({ url, secret });
const suffix = `${Date.now()}-${randomBytes(4).toString("hex")}`;
const password = `PBHS!${randomBytes(10).toString("base64url")}aA9`;
const setupUrl = "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=setup";
const emails = {
  active: `phase83b-${suffix}@example.invalid`,
  missing: `phase83b-missing-${suffix}@example.invalid`,
  inactive: `phase83b-inactive-${suffix}@example.invalid`,
  unknown: `phase83b-unknown-${suffix}@example.invalid`,
};
const createdIds = [];
const safeResult = {
  project_ref: projectRef,
  scanner_gets_safe: false,
  dry_run_zero_mutation: false,
  identity_profile_singletons: false,
  duplicate_blocked: false,
  otp_verified: false,
  invalid_otp_denied: false,
  otp_replay_denied: false,
  active_profile_allowed: false,
  missing_profile_denied: false,
  inactive_profile_denied: false,
  unprovisioned_denied: false,
  password_policy_enforced: false,
  password_set: false,
  forced_signout: false,
  normal_password_login: false,
  modern_credentials_only: false,
  sensitive_output_redacted: false,
  cleanup_complete: false,
};

async function rest(path, { token = secret, key = secret, method = "GET", body, prefer } = {}) {
  const response = await fetch(`${url}${path}`, { method, headers: { apikey: key, Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(prefer ? { Prefer: prefer } : {}) }, body: body == null ? undefined : JSON.stringify(body) });
  const text = await response.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  return { ok: response.ok, status: response.status, data };
}
async function generateOtp(email) {
  const response = await rest("/auth/v1/admin/generate_link", { method: "POST", body: { type: "magiclink", email } });
  const code = response.data?.email_otp || response.data?.properties?.email_otp;
  if (!response.ok || !code) throw new Error(`Trusted OTP generation failed with HTTP ${response.status}.`);
  return code;
}
async function verifyOtp(email, token) {
  return rest("/auth/v1/verify", { token: publishable, key: publishable, method: "POST", body: { email, token, type: "email" } });
}
async function createSynthetic(email, active) {
  const user = await admin.createUser(email, "Phase 8.3B Synthetic Teacher");
  createdIds.push(user.id);
  if (active !== null) await admin.createProfile({ user_id: user.id, email, display_name: "Phase 8.3B Synthetic Teacher", role: "teacher", hod_scope: null, active });
  return user;
}

try {
  const scan1 = await fetch(setupUrl, { redirect: "manual" });
  const scan2 = await fetch(setupUrl, { redirect: "manual" });
  safeResult.scanner_gets_safe = scan1.status === 200 && scan2.status === 200;

  const record = { email: emails.active, display_name: "Phase 8.3B Synthetic Teacher", role: "teacher", hod_scope: null };
  const beforeUsers = await admin.listUsersByEmail(emails.active);
  const beforeProfiles = await admin.listProfilesByEmail(emails.active);
  const dryRun = await provisionStaff({ admin, input: record, redirectTo: setupUrl, dryRun: true });
  safeResult.dry_run_zero_mutation = dryRun.state === "new" && beforeUsers.length === 0 && beforeProfiles.length === 0;
  const provisioned = await provisionStaff({ admin, input: record, redirectTo: setupUrl });
  createdIds.push(provisioned.auth_user_id);
  const users = await admin.listUsersByEmail(emails.active);
  const profiles = await admin.listProfilesByEmail(emails.active);
  safeResult.identity_profile_singletons = users.length === 1 && profiles.length === 1 && profiles[0].active === true;
  try { await provisionStaff({ admin, input: record, redirectTo: setupUrl }); } catch (error) { safeResult.duplicate_blocked = error instanceof ProvisioningError && error.code === "ALREADY_PROVISIONED"; }

  const otp = await generateOtp(emails.active);
  safeResult.invalid_otp_denied = !(await verifyOtp(emails.active, "00000000")).ok;
  const verified = await verifyOtp(emails.active, otp);
  const setupToken = verified.data?.access_token;
  safeResult.otp_verified = verified.ok && Boolean(setupToken);
  const activeProfile = await rest("/rest/v1/rpc/pbhs_active_profile_status", { token: setupToken, key: publishable, method: "POST", body: {} });
  safeResult.active_profile_allowed = activeProfile.ok && activeProfile.data === true;
  safeResult.password_policy_enforced = !(await rest("/auth/v1/user", { token: setupToken, key: publishable, method: "PUT", body: { password: "weakpass" } })).ok;
  safeResult.password_set = (await rest("/auth/v1/user", { token: setupToken, key: publishable, method: "PUT", body: { password } })).ok;
  safeResult.forced_signout = (await rest("/auth/v1/logout", { token: setupToken, key: publishable, method: "POST" })).ok;
  safeResult.otp_replay_denied = !(await verifyOtp(emails.active, otp)).ok;
  safeResult.normal_password_login = (await rest("/auth/v1/token?grant_type=password", { token: publishable, key: publishable, method: "POST", body: { email: emails.active, password } })).ok;

  await createSynthetic(emails.missing, null);
  const missingSession = await verifyOtp(emails.missing, await generateOtp(emails.missing));
  const missingProfile = await rest("/rest/v1/rpc/pbhs_active_profile_status", { token: missingSession.data?.access_token, key: publishable, method: "POST", body: {} });
  safeResult.missing_profile_denied = missingProfile.ok && missingProfile.data === false;
  await createSynthetic(emails.inactive, false);
  const inactiveSession = await verifyOtp(emails.inactive, await generateOtp(emails.inactive));
  const inactiveProfile = await rest("/rest/v1/rpc/pbhs_active_profile_status", { token: inactiveSession.data?.access_token, key: publishable, method: "POST", body: {} });
  safeResult.inactive_profile_denied = inactiveProfile.ok && inactiveProfile.data === false;
  safeResult.unprovisioned_denied = !(await rest("/auth/v1/otp", { token: publishable, key: publishable, method: "POST", body: { email: emails.unknown, create_user: false } })).ok;

  const redactionProbe = JSON.stringify(redactSensitiveValue({ secret, password, token: otp, Authorization: `Bearer ${secret}` }));
  safeResult.sensitive_output_redacted = ![secret, password, otp].some((value) => redactionProbe.includes(value));
  safeResult.modern_credentials_only = credential.source === "SUPABASE_SECRET_KEY" && secret.startsWith("sb_secret_") && publishable.startsWith("sb_publishable_");
} finally {
  if (createdIds.length) await rest(`/rest/v1/department_profiles?user_id=in.(${createdIds.join(",")})`, { method: "DELETE" });
  for (const id of createdIds) await rest(`/auth/v1/admin/users/${id}`, { method: "DELETE" });
  safeResult.cleanup_complete = (await Promise.all(Object.values(emails).slice(0, 3).map((email) => admin.listUsersByEmail(email)))).every((rows) => rows.length === 0);
}

if (!Object.entries(safeResult).filter(([key]) => key !== "project_ref").every(([, value]) => value === true)) throw new Error(`Hosted validation failed: ${JSON.stringify(redactSensitiveValue(safeResult))}`);
console.log(JSON.stringify(redactSensitiveValue(safeResult), null, 2));
