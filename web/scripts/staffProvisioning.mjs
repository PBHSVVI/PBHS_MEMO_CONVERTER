const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const ROLES = new Set(["teacher", "hod"]);
const HOD_SCOPES = new Set(["mathematics", "fs_mathematics"]);
const MODERN_SECRET_PREFIX = "sb_secret_";
const SENSITIVE_KEYS = new Set([
  "apikey", "authorization", "password", "access_token", "refresh_token",
  "token", "token_hash", "action_link", "actionlink", "invite_link",
  "invitelink", "secret", "staff_code", "staffcode", "temporary_password",
  "supabase_secret_key", "supabase_service_role_key",
]);

export function redactSensitiveText(value) {
  return String(value ?? "")
    .replace(/https?:\/\/[^\s"'<>]*(?:[?&#](?:token|token_hash|access_token|refresh_token)=[^\s"'<>]*)/gi, "[REDACTED_INVITE_LINK]")
    .replace(/sb_secret_[A-Za-z0-9._-]+/gi, "[REDACTED_SUPABASE_SECRET]")
    .replace(/\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[REDACTED_JWT]")
    .replace(/\bBearer\s+[^\s,;}]+/gi, "Bearer [REDACTED]")
    .replace(/((?:password|apikey|authorization)\s*[=:]\s*)[^\s,;}]+/gi, "$1[REDACTED]");
}

export function redactSensitiveValue(value, key = "") {
  const normalizedKey = String(key).toLowerCase().replace(/[-\s]/g, "_");
  if (SENSITIVE_KEYS.has(normalizedKey)) return "[REDACTED]";
  if (typeof value === "string") return redactSensitiveText(value);
  if (Array.isArray(value)) return value.map((entry) => redactSensitiveValue(entry));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([entryKey, entryValue]) =>
      [entryKey, redactSensitiveValue(entryValue, entryKey)]));
  }
  return value;
}

export function selectTrustedCredential(environment = {}) {
  const modern = String(environment.SUPABASE_SECRET_KEY || "").trim();
  const legacy = String(environment.SUPABASE_SERVICE_ROLE_KEY || "").trim();
  if (modern) {
    if (!modern.startsWith(MODERN_SECRET_PREFIX)) {
      throw new ProvisioningError(
        "INVALID_ADMIN_SECRET",
        "SUPABASE_SECRET_KEY must contain a modern Supabase secret key.",
      );
    }
    return { secret: modern, source: "SUPABASE_SECRET_KEY", deprecated: false };
  }
  if (legacy) {
    return { secret: legacy, source: "SUPABASE_SERVICE_ROLE_KEY", deprecated: true };
  }
  throw new ProvisioningError(
    "MISSING_ADMIN_SECRET",
    "Set SUPABASE_SECRET_KEY in the trusted process environment.",
  );
}

export class ProvisioningError extends Error {
  constructor(code, message, action = "Review the staff record before trying again.") {
    super(message);
    this.name = "ProvisioningError";
    this.code = code;
    this.action = action;
  }
}

export function validateStaffRecord(input) {
  const record = {
    email: String(input?.email || "").trim().toLowerCase(),
    display_name: String(input?.display_name || input?.displayName || "").trim(),
    role: String(input?.role || "").trim().toLowerCase(),
    hod_scope: input?.hod_scope == null || input?.hod_scope === ""
      ? null
      : String(input.hod_scope).trim().toLowerCase(),
  };
  const errors = [];
  if (!EMAIL_RE.test(record.email) || record.email.length > 320) errors.push("Enter a valid staff email address.");
  if (!record.display_name || record.display_name.length > 120 || /[\u0000-\u001f\u007f]/.test(record.display_name)) {
    errors.push("Display name must contain 1–120 printable characters.");
  }
  if (!ROLES.has(record.role)) errors.push("Role must be teacher or hod.");
  if (record.role === "teacher" && record.hod_scope !== null) errors.push("Teachers must not have an HOD scope.");
  if (record.role === "hod" && !HOD_SCOPES.has(record.hod_scope)) {
    errors.push("An HOD must have mathematics or fs_mathematics scope.");
  }
  if (errors.length) throw new ProvisioningError("INVALID_INPUT", errors.join(" "));
  return record;
}

export function validateInviteRedirect(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new ProvisioningError("INVALID_REDIRECT", "Invite redirect URL is invalid.");
  }
  const hosted = url.protocol === "https:" && url.hostname === "pbhsvvi.github.io" &&
    url.pathname === "/PBHS_MEMO_CONVERTER/teacher-app/";
  const local = ["localhost", "127.0.0.1"].includes(url.hostname) && ["http:", "https:"].includes(url.protocol);
  if (!hosted && !local) {
    throw new ProvisioningError("INVALID_REDIRECT", "Invite redirect must use the PBHS Teacher App or local development host.");
  }
  url.searchParams.set("onboarding", "setup");
  return url.toString();
}

export function validateTemporaryPassword(value) {
  const password = String(value || "");
  if (password.length < 12 || !/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/[0-9]/.test(password) || !/[^A-Za-z0-9]/.test(password)) {
    throw new ProvisioningError(
      "INVALID_TEMPORARY_PASSWORD",
      "The runtime staff code must meet the configured 12-character mixed-character password policy.",
    );
  }
  return password;
}

function isConfirmed(user) {
  return Boolean(user?.email_confirmed_at || user?.confirmed_at);
}

function profileDifferences(profile, record) {
  if (!profile) return [];
  return ["display_name", "email", "role", "hod_scope"].filter((field) =>
    (profile[field] ?? null) !== (record[field] ?? null));
}

export function classifyProvisioningState(recordInput, users = [], profiles = []) {
  const record = validateStaffRecord(recordInput);
  const matchingUsers = users.filter((user) => String(user.email || "").trim().toLowerCase() === record.email);
  const emailProfiles = profiles.filter((profile) => String(profile.email || "").trim().toLowerCase() === record.email);
  if (matchingUsers.length > 1) {
    throw new ProvisioningError("DUPLICATE_AUTH", "More than one Auth identity uses this email.", "Resolve the duplicate identities in Supabase Auth.");
  }
  if (emailProfiles.length > 1) {
    throw new ProvisioningError("DUPLICATE_PROFILE", "More than one department profile uses this email.", "Resolve the duplicate profiles before provisioning.");
  }
  const user = matchingUsers[0] || null;
  const profile = user
    ? profiles.find((candidate) => candidate.user_id === user.id) || emailProfiles[0] || null
    : emailProfiles[0] || null;
  if (!user && profile) {
    throw new ProvisioningError("PROFILE_WITHOUT_AUTH", "A department profile exists without the matching Auth identity.", "Inspect the profile ownership before creating an account.");
  }
  if (user && profile && profile.user_id !== user.id) {
    throw new ProvisioningError("AUTH_PROFILE_MISMATCH", "The email is linked to a different profile UUID.", "Resolve the identity mismatch before changing any profile.");
  }
  if (!user) return { record, state: "new", user: null, profile: null, planned: ["create_auth_identity", "create_profile"] };
  if (!profile) {
    return {
      record,
      state: isConfirmed(user) ? "confirmed_auth_profile_missing" : "invited_auth_profile_missing",
      user,
      profile: null,
      planned: ["explicit_profile_repair"],
    };
  }
  const differences = profileDifferences(profile, record);
  if (!profile.active) return { record, state: "inactive_profile", user, profile, differences, planned: ["admin_review"] };
  if (differences.length) return { record, state: "profile_conflict", user, profile, differences, planned: ["explicit_profile_update"] };
  if (isConfirmed(user)) return { record, state: "active_confirmed", user, profile, differences: [], planned: [] };
  return { record, state: "setup_pending", user, profile, differences: [], planned: ["send_setup_page"] };
}

export function safeProvisioningReport(classification, dryRun = true, temporaryPasswordSupplied = false) {
  return {
    dry_run: dryRun,
    email: classification.record.email,
    display_name: classification.record.display_name,
    role: classification.record.role,
    hod_scope: classification.record.hod_scope,
    state: classification.state,
    planned_actions: classification.planned,
    auth_user_id: classification.user?.id || null,
    profile_user_id: classification.profile?.user_id || null,
    profile_differences: classification.differences || [],
    temporary_password_supplied: Boolean(temporaryPasswordSupplied),
  };
}

export async function provisionStaff({
  admin,
  input,
  redirectTo,
  dryRun = false,
  reissueInvite = false,
  repairProfile = false,
  updateProfile = false,
  temporaryPassword = null,
  temporaryPasswordRecovery = false,
}) {
  const record = validateStaffRecord(input);
  const runtimePassword = temporaryPassword == null ? null : validateTemporaryPassword(temporaryPassword);
  if (temporaryPasswordRecovery && !runtimePassword) {
    throw new ProvisioningError("TEMPORARY_PASSWORD_REQUIRED", "Temporary-password recovery requires a runtime staff code.");
  }
  const redirect = validateInviteRedirect(redirectTo);
  const users = await admin.listUsersByEmail(record.email);
  const emailProfiles = await admin.listProfilesByEmail(record.email);
  const userProfiles = users[0] && admin.listProfilesByUserId
    ? await admin.listProfilesByUserId(users[0].id)
    : [];
  const profiles = [...emailProfiles, ...userProfiles.filter((candidate) =>
    !emailProfiles.some((existing) => existing.user_id === candidate.user_id))];
  let current = classifyProvisioningState(record, users, profiles);
  if (runtimePassword) {
    const planned = current.state === "new"
      ? ["create_auth_identity", "set_temporary_password", "create_profile", "require_password_change"]
      : temporaryPasswordRecovery && current.state === "active_confirmed"
        ? ["preserve_auth_identity", "set_temporary_password", "require_password_change"]
        : current.planned;
    current = { ...current, planned };
  }
  if (dryRun) return safeProvisioningReport(current, true, Boolean(runtimePassword));

  if (current.state === "new") {
    const user = await admin.createUser(record.email, record.display_name, runtimePassword);
    if (!user?.id) {
      throw new ProvisioningError("CREATE_USER_RESPONSE_INVALID", "Supabase did not return a complete Auth identity.");
    }
    await admin.setSafeIdentity(user.id, record.display_name, user.app_metadata);
    const profile = { user_id: user.id, ...record, active: true, must_change_password: Boolean(runtimePassword) };
    await admin.createProfile(profile);
    current = { ...current, state: runtimePassword ? "temporary_password_ready" : "setup_ready", user, profile, planned: [] };
    return { ...safeProvisioningReport(current, false, Boolean(runtimePassword)), setup_url: redirect, invite_generated: false };
  }

  if (["confirmed_auth_profile_missing", "invited_auth_profile_missing"].includes(current.state)) {
    if (!repairProfile) {
      throw new ProvisioningError("PROFILE_REPAIR_REQUIRED", "The Auth identity exists but its department profile is missing.", "Review the UUID, then rerun with --repair-profile.");
    }
    await admin.setSafeIdentity(current.user.id, record.display_name, current.user.app_metadata);
    if (runtimePassword) await admin.setTemporaryPassword(current.user.id, runtimePassword);
    await admin.createProfile({ user_id: current.user.id, ...record, active: true, must_change_password: Boolean(runtimePassword) });
    return { ...safeProvisioningReport({ ...current, state: "profile_repaired", profile: { user_id: current.user.id } }, false, Boolean(runtimePassword)), invite_generated: false };
  }

  if (current.state === "profile_conflict") {
    if (!updateProfile) {
      throw new ProvisioningError("PROFILE_UPDATE_REQUIRED", `Existing profile differs in: ${current.differences.join(", ")}.`, "Confirm the identity and rerun with --update-profile.");
    }
    await admin.updateProfile(current.user.id, record);
    await admin.setSafeIdentity(current.user.id, record.display_name, current.user.app_metadata);
    return { ...safeProvisioningReport({ ...current, state: "profile_updated", differences: [] }, false, false), invite_generated: false };
  }

  if (current.state === "setup_pending" && reissueInvite) {
    throw new ProvisioningError("RAW_INVITES_DISABLED", "Raw one-time invitation links are disabled.", "Send the permanent PBHS account setup page instead.");
  }

  if (current.state === "inactive_profile") {
    throw new ProvisioningError("INACTIVE_PROFILE", "This department profile is inactive.", "An administrator must review reactivation separately.");
  }
  if (current.state === "active_confirmed") {
    if (runtimePassword && temporaryPasswordRecovery) {
      // Fail closed: establish the data-access gate before replacing the Auth
      // password. If Auth rejects the password, the account remains gated.
      await admin.setMustChangePassword(current.user.id, true);
      await admin.setTemporaryPassword(current.user.id, runtimePassword);
      return {
        ...safeProvisioningReport({ ...current, state: "temporary_password_reset", planned: [] }, false, true),
        invite_generated: false,
      };
    }
    throw new ProvisioningError("ALREADY_PROVISIONED", "This staff account is already active and confirmed.", "Use the normal sign-in or password-recovery process.");
  }
  throw new ProvisioningError("NO_SAFE_ACTION", "No safe provisioning action was selected.");
}

export function createSupabaseAdmin({ url, secret, fetchImpl = fetch }) {
  const base = String(url || "").replace(/\/$/, "");
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/i.test(base)) throw new ProvisioningError("INVALID_SUPABASE_URL", "SUPABASE_URL is invalid.");
  if (!secret) throw new ProvisioningError("MISSING_ADMIN_SECRET", "A trusted Supabase admin secret is required.");
  const headers = { apikey: secret, Authorization: `Bearer ${secret}`, "Content-Type": "application/json" };

  async function request(path, options = {}) {
    const response = await fetchImpl(`${base}${path}`, { ...options, headers: { ...headers, ...(options.headers || {}) } });
    if (!response.ok) throw new ProvisioningError("ADMIN_API_FAILED", `Trusted Supabase operation failed with HTTP ${response.status}.`);
    if (response.status === 204) return null;
    return response.json();
  }

  return {
    async listUsersByEmail(email) {
      const matches = [];
      for (let page = 1; page <= 100; page += 1) {
        const result = await request(`/auth/v1/admin/users?page=${page}&per_page=100`);
        const users = result?.users || [];
        matches.push(...users.filter((user) => String(user.email || "").toLowerCase() === email));
        if (users.length < 100) break;
      }
      return matches;
    },
    async listProfilesByEmail(email) {
      return request(`/rest/v1/department_profiles?email=eq.${encodeURIComponent(email)}&select=user_id,display_name,email,role,hod_scope,active`);
    },
    async listProfilesByUserId(userId) {
      return request(`/rest/v1/department_profiles?user_id=eq.${encodeURIComponent(userId)}&select=user_id,display_name,email,role,hod_scope,active`);
    },
    async createUser(email, displayName, temporaryPassword = null) {
      const body = {
        email,
        email_confirm: true,
        app_metadata: { pbhs_display_name: displayName },
      };
      if (temporaryPassword) body.password = temporaryPassword;
      const result = await request("/auth/v1/admin/users", {
        method: "POST",
        body: JSON.stringify(body),
      });
      return result?.user || (result?.id && result?.email ? result : null);
    },
    async setSafeIdentity(userId, displayName, currentAppMetadata = {}) {
      return request(`/auth/v1/admin/users/${encodeURIComponent(userId)}`, {
        method: "PUT",
        body: JSON.stringify({ app_metadata: { ...(currentAppMetadata || {}), pbhs_display_name: displayName } }),
      });
    },
    async setTemporaryPassword(userId, temporaryPassword) {
      return request(`/auth/v1/admin/users/${encodeURIComponent(userId)}`, {
        method: "PUT",
        body: JSON.stringify({ password: temporaryPassword }),
      });
    },
    async createProfile(profile) {
      return request("/rest/v1/department_profiles", {
        method: "POST",
        headers: { Prefer: "return=representation" },
        body: JSON.stringify(profile),
      });
    },
    async updateProfile(userId, record) {
      return request(`/rest/v1/department_profiles?user_id=eq.${encodeURIComponent(userId)}`, {
        method: "PATCH",
        headers: { Prefer: "return=representation" },
        body: JSON.stringify(record),
      });
    },
    async setMustChangePassword(userId, required) {
      return request(`/rest/v1/department_profiles?user_id=eq.${encodeURIComponent(userId)}`, {
        method: "PATCH",
        headers: { Prefer: "return=minimal" },
        body: JSON.stringify({ must_change_password: Boolean(required) }),
      });
    },
  };
}
