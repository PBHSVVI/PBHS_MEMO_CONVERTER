import { randomBytes, randomUUID } from "node:crypto";
import process from "node:process";
import { ProvisioningError, createSupabaseAdmin, provisionStaff, redactSensitiveValue, selectTrustedCredential } from "./staffProvisioning.mjs";

const projectRef = process.env.PBHS_VALIDATION_PROJECT_REF;
const url = process.env.SUPABASE_URL;
const publishable = process.env.SUPABASE_PUBLISHABLE_KEY;
if (projectRef !== "wgkydsildfmbqzvicuwm" || url !== `https://${projectRef}.supabase.co`) {
  throw new Error("Hosted validation is locked to the Phase 8.3 validation project.");
}
if (!publishable?.startsWith("sb_publishable_")) {
  throw new Error("SUPABASE_PUBLISHABLE_KEY must contain a modern Supabase publishable key.");
}
const credential = selectTrustedCredential({ SUPABASE_SECRET_KEY: process.env.SUPABASE_SECRET_KEY });
const secret = credential.secret;

const suffix = `${Date.now()}-${randomBytes(4).toString("hex")}`;
const email = `phase83b-${suffix}@example.invalid`;
const password = `PBHS!${randomBytes(10).toString("base64url")}aA9`;
const redirectTo = "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=invite";
const record = { email, display_name: "Phase 8.3B Synthetic Teacher", role: "teacher", hod_scope: null };
const admin = createSupabaseAdmin({ url, secret });
const safeResult = {
  project_ref: projectRef,
  synthetic_domain: "example.invalid",
  dry_run_zero_mutation: false,
  identity_count: null,
  profile_count: null,
  profile_role_scope_correct: false,
  invite_generated: false,
  redirect_correct: false,
  redirect_observed: null,
  invite_accepted: false,
  password_set: false,
  server_password_policy_rejects_weak: false,
  normal_login: false,
  library_read: false,
  owner_write: false,
  cross_owner_write_blocked: false,
  browser_profile_update_blocked: false,
  duplicate_blocked: false,
  reissue_no_duplicate: false,
  user_metadata_not_authorization: false,
  sensitive_output_redacted: false,
  modern_credentials_only: false,
};

async function rest(path, { token = secret, key = secret, method = "GET", body, prefer } = {}) {
  const response = await fetch(`${url}${path}`, {
    method,
    headers: {
      apikey: key,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(prefer ? { Prefer: prefer } : {}),
    },
    body: body == null ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  return { ok: response.ok, status: response.status, data };
}

const beforeUsers = await admin.listUsersByEmail(email);
const beforeProfiles = await admin.listProfilesByEmail(email);
const dryRun = await provisionStaff({ admin, input: record, redirectTo, dryRun: true });
const afterDryUsers = await admin.listUsersByEmail(email);
const afterDryProfiles = await admin.listProfilesByEmail(email);
safeResult.dry_run_zero_mutation = dryRun.state === "new" && beforeUsers.length === 0 && beforeProfiles.length === 0 && afterDryUsers.length === 0 && afterDryProfiles.length === 0;

let actionLink = null;
await provisionStaff({ admin, input: record, redirectTo, onInvite: async (value) => { actionLink = value; } });
safeResult.invite_generated = Boolean(actionLink);

let users = await admin.listUsersByEmail(email);
let profiles = await admin.listProfilesByEmail(email);
safeResult.identity_count = users.length;
safeResult.profile_count = profiles.length;
safeResult.profile_role_scope_correct = profiles.length === 1 && profiles[0].role === "teacher" && profiles[0].hod_scope === null && profiles[0].active === true;

try {
  await provisionStaff({ admin, input: record, redirectTo });
} catch (error) {
  safeResult.duplicate_blocked = error instanceof ProvisioningError && error.code === "NO_SAFE_ACTION";
}

let reissuedLink = null;
await provisionStaff({ admin, input: record, redirectTo, reissueInvite: true, onInvite: async (value) => { reissuedLink = value; } });
users = await admin.listUsersByEmail(email);
profiles = await admin.listProfilesByEmail(email);
safeResult.reissue_no_duplicate = Boolean(reissuedLink) && users.length === 1 && profiles.length === 1;
actionLink = reissuedLink;

const verify = await fetch(actionLink, { redirect: "manual" });
const location = verify.headers.get("location");
if (!location) throw new Error(`Invitation verification did not redirect (HTTP ${verify.status}).`);
const redirected = new URL(location);
safeResult.redirect_observed = { origin: redirected.origin, path: redirected.pathname, onboarding: redirected.searchParams.get("onboarding") };
safeResult.redirect_correct = redirected.origin === "https://pbhsvvi.github.io" && redirected.pathname === "/PBHS_MEMO_CONVERTER/teacher-app/" && redirected.searchParams.get("onboarding") === "invite";
const fragment = new URLSearchParams(redirected.hash.replace(/^#/, ""));
const inviteAccessToken = fragment.get("access_token");
safeResult.invite_accepted = Boolean(inviteAccessToken) && fragment.get("type") === "invite";
if (!inviteAccessToken) throw new Error("Invitation redirect did not establish an invite session.");

const update = await rest("/auth/v1/user", { token: inviteAccessToken, key: publishable, method: "PUT", body: { password } });
safeResult.password_set = update.ok;
await rest("/auth/v1/logout", { token: inviteAccessToken, key: publishable, method: "POST" });

const login = await rest("/auth/v1/token?grant_type=password", { token: publishable, key: publishable, method: "POST", body: { email, password } });
const userToken = login.data?.access_token;
safeResult.normal_login = login.ok && Boolean(userToken);
if (!userToken) throw new Error("Normal password login failed after invitation acceptance.");
const weakPassword = await rest("/auth/v1/user", { token: userToken, key: publishable, method: "PUT", body: { password: "weakpass" } });
safeResult.server_password_policy_rejects_weak = !weakPassword.ok;

const metadataUpdate = await rest("/auth/v1/user", { token: userToken, key: publishable, method: "PUT", body: { data: { role: "hod", hod_scope: "fs_mathematics" } } });
const profileAfterMetadata = await admin.listProfilesByEmail(email);
safeResult.user_metadata_not_authorization = metadataUpdate.ok && profileAfterMetadata.length === 1 && profileAfterMetadata[0].role === "teacher" && profileAfterMetadata[0].hod_scope === null;

const jobId = randomUUID();
const job = await rest("/rest/v1/jobs", {
  token: userToken, key: publishable, method: "POST", prefer: "return=representation",
  body: { id: jobId, user_id: users[0].id, status: "queued", stage: "upload", source_filename: "phase83b-synthetic.docx" },
});
safeResult.owner_write = job.ok && Array.isArray(job.data) && job.data.length === 1;

const crossOwner = await rest("/rest/v1/jobs", {
  token: userToken, key: publishable, method: "POST", prefer: "return=representation",
  body: {
    id: randomUUID(), user_id: randomUUID(), status: "queued", stage: "upload",
    source_filename: "phase83b-cross-owner-denial.docx",
  },
});
safeResult.cross_owner_write_blocked = !crossOwner.ok && [401, 403].includes(crossOwner.status);

const now = new Date().toISOString();
const summary = await rest("/rest/v1/paper_library_summary", {
  method: "POST", prefer: "return=minimal",
  body: {
    job_id: jobId, owner_user_id: users[0].id, subject_scope: "mathematics", subject_display: "MATHEMATICS",
    workflow_bucket: "in_progress", status_source: "queued", stage_source: "upload", source_filename: "phase83b-synthetic.docx",
    created_at: now, updated_at: now,
  },
});
if (!summary.ok) throw new Error(`Synthetic summary setup failed with HTTP ${summary.status}.`);
const library = await rest(`/rest/v1/paper_library_summary?job_id=eq.${jobId}&select=job_id,subject_scope`, { token: userToken, key: publishable });
safeResult.library_read = library.ok && library.data?.length === 1 && library.data[0].subject_scope === "mathematics";

const browserProfileUpdate = await rest(`/rest/v1/department_profiles?user_id=eq.${users[0].id}`, {
  token: userToken, key: publishable, method: "PATCH", body: { role: "hod", hod_scope: "fs_mathematics" }, prefer: "return=representation",
});
safeResult.browser_profile_update_blocked = !browserProfileUpdate.ok;

const redactionProbe = JSON.stringify(redactSensitiveValue({
  secret,
  apikey: secret,
  Authorization: `Bearer ${secret}`,
  password,
  action_link: actionLink,
}));
safeResult.sensitive_output_redacted = ![secret, password, actionLink].some((value) => redactionProbe.includes(value));
safeResult.modern_credentials_only = credential.source === "SUPABASE_SECRET_KEY" &&
  secret.startsWith("sb_secret_") && publishable.startsWith("sb_publishable_");

if (!Object.entries(safeResult).filter(([key]) => !["project_ref", "synthetic_domain", "identity_count", "profile_count", "redirect_observed"].includes(key)).every(([, value]) => value === true)) {
  throw new Error(`Hosted validation failed: ${JSON.stringify(redactSensitiveValue(safeResult))}`);
}
console.log(JSON.stringify(redactSensitiveValue(safeResult), null, 2));
