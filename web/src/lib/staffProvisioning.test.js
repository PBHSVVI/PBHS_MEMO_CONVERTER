import { describe, expect, it, vi } from "vitest";
import {
  ProvisioningError,
  classifyProvisioningState,
  provisionStaff,
  redactSensitiveText,
  redactSensitiveValue,
  selectTrustedCredential,
  validateStaffRecord,
} from "../../scripts/staffProvisioning.mjs";

const teacher = { email: "synthetic@example.invalid", display_name: "Synthetic Teacher", role: "teacher", hod_scope: null };
const user = { id: "00000000-0000-4000-8000-000000000001", email: teacher.email, invited_at: "2026-10-12T00:00:00Z" };
const profile = { user_id: user.id, ...teacher, active: true };

function admin(overrides = {}) {
  return {
    listUsersByEmail: vi.fn(async () => []),
    listProfilesByEmail: vi.fn(async () => []),
    listProfilesByUserId: vi.fn(async () => []),
    createUser: vi.fn(async () => user),
    setSafeIdentity: vi.fn(async () => {}),
    createProfile: vi.fn(async () => {}),
    updateProfile: vi.fn(async () => {}),
    ...overrides,
  };
}

describe("trusted staff provisioning", () => {
  it("prefers a modern secret and marks the legacy fallback deprecated", () => {
    const modern = ["sb", "secret", "modern-value"].join("_");
    const legacy = ["eyJlegacy", "payload", "signature"].join(".");
    expect(selectTrustedCredential({ SUPABASE_SECRET_KEY: modern, SUPABASE_SERVICE_ROLE_KEY: legacy }))
      .toEqual({ secret: modern, source: "SUPABASE_SECRET_KEY", deprecated: false });
    expect(selectTrustedCredential({ SUPABASE_SERVICE_ROLE_KEY: legacy }))
      .toEqual({ secret: legacy, source: "SUPABASE_SERVICE_ROLE_KEY", deprecated: true });
    expect(() => selectTrustedCredential({ SUPABASE_SECRET_KEY: "legacy-shaped-value" }))
      .toThrowError(/modern Supabase secret key/);
  });

  it("redacts server credentials, headers, passwords and invite tokens", () => {
    const modern = ["sb", "secret", "do-not-log"].join("_");
    const jwt = ["eyJlegacy", "payloadvalue", "signaturevalue"].join(".");
    const invite = "https://validation.supabase.co/auth/v1/verify?token=invite-value&type=invite";
    const output = JSON.stringify(redactSensitiveValue({
      secret: modern,
      Authorization: `Bearer ${jwt}`,
      apikey: modern,
      password: "DoNotLog!123",
      action_link: invite,
      nested: `failure ${modern} ${jwt} ${invite}`,
    }));
    for (const sensitive of [modern, jwt, "DoNotLog!123", "invite-value", "validation.supabase.co/auth/v1/verify"]) expect(output).not.toContain(sensitive);
    expect(output).toContain("[REDACTED]");
    expect(redactSensitiveText(`Authorization=Bearer ${modern}`)).not.toContain(modern);
  });

  it("validates roles and HOD scopes deterministically", () => {
    expect(validateStaffRecord(teacher)).toEqual(teacher);
    expect(validateStaffRecord({ ...teacher, role: "hod", hod_scope: "mathematics" }).hod_scope).toBe("mathematics");
    expect(() => validateStaffRecord({ ...teacher, role: "teacher", hod_scope: "mathematics" })).toThrow(ProvisioningError);
    expect(() => validateStaffRecord({ ...teacher, role: "hod" })).toThrow(ProvisioningError);
  });

  it("dry run reports intended changes and causes zero mutation", async () => {
    const client = admin();
    const result = await provisionStaff({ admin: client, input: teacher, redirectTo: "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/", dryRun: true });
    expect(result).toMatchObject({ dry_run: true, state: "new", planned_actions: ["create_auth_identity", "create_profile"] });
    expect(client.createUser).not.toHaveBeenCalled();
    expect(client.createProfile).not.toHaveBeenCalled();
    expect(client.setSafeIdentity).not.toHaveBeenCalled();
  });

  it("creates one confirmed Auth identity and one profile without raw invite material", async () => {
    const client = admin();
    const result = await provisionStaff({ admin: client, input: teacher, redirectTo: "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/" });
    expect(client.createUser).toHaveBeenCalledWith(teacher.email, teacher.display_name);
    expect(client.createProfile).toHaveBeenCalledWith({ user_id: user.id, ...teacher, active: true });
    expect(client.setSafeIdentity).toHaveBeenCalledWith(user.id, teacher.display_name, undefined);
    expect(result).toMatchObject({ state: "setup_ready", invite_generated: false });
    expect(result.setup_url).toContain("onboarding=setup");
    expect(JSON.stringify(result)).not.toMatch(/token=|action_link|invite_link/i);
  });

  it("creates a confirmed user through the Admin REST API without a password or invite URL", async () => {
    const response = { ...user };
    const fetchImpl = vi.fn(async (url) => ({ ok: true, status: 200, json: async () => response }));
    const { createSupabaseAdmin } = await import("../../scripts/staffProvisioning.mjs");
    const restAdmin = createSupabaseAdmin({ url: "https://validation.supabase.co", secret: "runtime-only", fetchImpl });
    const created = await restAdmin.createUser(teacher.email, teacher.display_name);
    expect(created).toEqual(expect.objectContaining({ id: user.id }));
    const request = fetchImpl.mock.calls[0];
    expect(request[0]).toContain("/auth/v1/admin/users");
    expect(JSON.parse(request[1].body)).toEqual({
      email: teacher.email,
      email_confirm: true,
      app_metadata: { pbhs_display_name: teacher.display_name },
    });
    expect(request[1].body).not.toContain("password");
  });

  it("does not silently duplicate or alter a confirmed account", async () => {
    const confirmed = { ...user, email_confirmed_at: "2026-10-12T01:00:00Z" };
    const client = admin({ listUsersByEmail: vi.fn(async () => [confirmed]), listProfilesByEmail: vi.fn(async () => [profile]) });
    await expect(provisionStaff({ admin: client, input: teacher, redirectTo: "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/" })).rejects.toMatchObject({ code: "ALREADY_PROVISIONED" });
    expect(client.createUser).not.toHaveBeenCalled();
  });

  it("requires explicit repair for an existing Auth user with no profile", async () => {
    const client = admin({ listUsersByEmail: vi.fn(async () => [user]) });
    await expect(provisionStaff({ admin: client, input: teacher, redirectTo: "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/" })).rejects.toMatchObject({ code: "PROFILE_REPAIR_REQUIRED" });
    expect(client.createProfile).not.toHaveBeenCalled();
  });

  it("refuses raw invite reissue for a pending existing identity", async () => {
    const client = admin({ listUsersByEmail: vi.fn(async () => [user]), listProfilesByEmail: vi.fn(async () => [profile]) });
    await expect(provisionStaff({ admin: client, input: teacher, redirectTo: "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/", reissueInvite: true }))
      .rejects.toMatchObject({ code: "RAW_INVITES_DISABLED" });
    expect(client.createUser).not.toHaveBeenCalled();
    expect(client.createProfile).not.toHaveBeenCalled();
    expect(client.updateProfile).not.toHaveBeenCalled();
  });

  it("detects UUID mismatch, inactive profile and scope changes", () => {
    expect(() => classifyProvisioningState(teacher, [user], [{ ...profile, user_id: "00000000-0000-4000-8000-000000000002" }])).toThrowError(/different profile UUID/);
    expect(classifyProvisioningState(teacher, [user], [{ ...profile, active: false }]).state).toBe("inactive_profile");
    const hod = { ...teacher, role: "hod", hod_scope: "mathematics" };
    expect(classifyProvisioningState(hod, [user], [profile])).toMatchObject({ state: "profile_conflict", differences: expect.arrayContaining(["role", "hod_scope"]) });
  });

  it("finds a profile by Auth UUID even when its stored email differs", async () => {
    const mismatched = { ...profile, email: "old-address@example.invalid" };
    const client = admin({ listUsersByEmail: vi.fn(async () => [user]), listProfilesByUserId: vi.fn(async () => [mismatched]) });
    const result = await provisionStaff({ admin: client, input: teacher, redirectTo: "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/", dryRun: true });
    expect(result).toMatchObject({ state: "profile_conflict", profile_differences: ["email"] });
  });
});
