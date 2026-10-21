import { describe, expect, it, vi } from "vitest";
import {
  ProvisioningError,
  deriveTemporaryPassword,
  parseProvisioningCsv,
  preflightStaffBatch,
  provisionStaffBatch,
  validateStaffBatch,
} from "../../scripts/staffProvisioning.mjs";

const redirectTo = "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/";

function inputs(count = 3) {
  return Array.from({ length: count }, (_, index) => ({
    display_name: `Synthetic Staff ${index + 1}`,
    email: `synthetic-${index + 1}@example.invalid`,
    role: index === count - 1 ? "hod" : "teacher",
    hod_scope: index === count - 1 ? "fs_mathematics" : "",
    staff_code: `zx${index + 1}`,
  }));
}

function statefulAdmin({ existing = new Map(), failProfileEmail = null } = {}) {
  const users = new Map();
  const profiles = new Map();
  for (const [email, value] of existing) {
    if (value.user) users.set(email, value.user);
    if (value.profile) profiles.set(email, value.profile);
  }
  let sequence = 0;
  return {
    users,
    profiles,
    listUsersByEmail: vi.fn(async (email) => users.has(email) ? [users.get(email)] : []),
    listProfilesByEmail: vi.fn(async (email) => profiles.has(email) ? [profiles.get(email)] : []),
    listProfilesByUserId: vi.fn(async (userId) => [...profiles.values()].filter((profile) => profile.user_id === userId)),
    createUser: vi.fn(async (email) => {
      const user = { id: `00000000-0000-4000-8000-${String(++sequence).padStart(12, "0")}`, email, email_confirmed_at: "2026-10-21T00:00:00Z" };
      users.set(email, user);
      return user;
    }),
    setSafeIdentity: vi.fn(async () => {}),
    createProfile: vi.fn(async (profile) => {
      if (profile.email === failProfileEmail) throw new ProvisioningError("SYNTHETIC_PROFILE_FAILURE", "Synthetic profile failure.");
      profiles.set(profile.email, profile);
    }),
    updateProfile: vi.fn(async () => {}),
    setTemporaryPassword: vi.fn(async () => {}),
    setMustChangePassword: vi.fn(async () => {}),
  };
}

function csv(records) {
  return [
    "display_name,email,role,hod_scope,staff_code",
    ...records.map((record) => [record.display_name, record.email, record.role, record.hod_scope, record.staff_code].join(",")),
  ].join("\n");
}

describe("trusted batch staff provisioning", () => {
  it("preserves single-record CSV behavior and requires explicit batch mode", () => {
    const source = csv(inputs(2));
    expect(() => parseProvisioningCsv(source)).toThrowError(/exactly one staff record/);
    expect(parseProvisioningCsv(source, { batch: true })).toHaveLength(2);
  });

  it("rejects duplicate normalized emails and duplicate staff codes", () => {
    const records = inputs(2);
    expect(() => validateStaffBatch([records[0], { ...records[1], email: records[0].email.toUpperCase() }]))
      .toThrowError(/repeats email/);
    expect(() => validateStaffBatch([records[0], { ...records[1], staff_code: records[0].staff_code.toUpperCase() }]))
      .toThrowError(/repeats a staff code/);
  });

  it("validates the complete batch before any live query or write", async () => {
    const client = statefulAdmin();
    const records = inputs(3);
    records[2] = { ...records[2], role: "teacher", hod_scope: "fs_mathematics" };
    await expect(preflightStaffBatch({ admin: client, inputs: records })).rejects.toMatchObject({ code: "INVALID_INPUT" });
    expect(client.listUsersByEmail).not.toHaveBeenCalled();
    expect(client.createUser).not.toHaveBeenCalled();
  });

  it("queries every row and aborts the complete write phase when one account exists", async () => {
    const records = inputs(3);
    const existingUser = { id: "00000000-0000-4000-8000-000000000099", email: records[1].email, email_confirmed_at: "2026-10-21T00:00:00Z" };
    const existingProfile = { user_id: existingUser.id, ...records[1], hod_scope: null, active: true, must_change_password: false };
    delete existingProfile.staff_code;
    const client = statefulAdmin({ existing: new Map([[records[1].email, { user: existingUser, profile: existingProfile }]]) });
    await expect(provisionStaffBatch({ admin: client, inputs: records, redirectTo })).rejects.toMatchObject({ code: "BATCH_PREFLIGHT_FAILED" });
    expect(client.listUsersByEmail).toHaveBeenCalledTimes(3);
    expect(client.createUser).not.toHaveBeenCalled();
    expect(client.setTemporaryPassword).not.toHaveBeenCalled();
  });

  it("aborts pre-write on an Auth/profile mismatch", async () => {
    const records = inputs(2);
    const user = { id: "00000000-0000-4000-8000-000000000098", email: records[0].email, email_confirmed_at: "2026-10-21T00:00:00Z" };
    const profile = { user_id: "00000000-0000-4000-8000-000000000097", ...records[0], hod_scope: null, active: true, must_change_password: true };
    delete profile.staff_code;
    const client = statefulAdmin({ existing: new Map([[records[0].email, { user, profile }]]) });
    await expect(provisionStaffBatch({ admin: client, inputs: records, redirectTo })).rejects.toMatchObject({ code: "BATCH_PREFLIGHT_FAILED" });
    expect(client.createUser).not.toHaveBeenCalled();
  });

  it("provisions and independently verifies every row before cleanup", async () => {
    const records = inputs(11);
    const client = statefulAdmin();
    const cleanup = vi.fn(async () => {});
    const result = await provisionStaffBatch({ admin: client, inputs: records, redirectTo, cleanup });
    expect(result.batch).toEqual(expect.objectContaining({ requested: 11, provisioned: 11, verified: 11, failed: 0, not_attempted: 0, burner_file_deleted: true }));
    expect(cleanup).toHaveBeenCalledOnce();
    expect(client.createUser).toHaveBeenCalledTimes(11);
    expect(client.createProfile).toHaveBeenCalledTimes(11);
    for (const profile of client.profiles.values()) expect(profile.must_change_password).toBe(true);
    expect(result.staff.slice(0, 10).every((entry) => entry.role === "teacher" && entry.hod_scope === null)).toBe(true);
    expect(result.staff[10]).toMatchObject({ role: "hod", hod_scope: "fs_mathematics", must_change_password: true, verified: true });
  });

  it("derives credentials only inside trusted calls and omits codes, passwords, and secrets from safe output", async () => {
    const records = inputs(2);
    const client = statefulAdmin();
    const result = await provisionStaffBatch({ admin: client, inputs: records, redirectTo, dryRun: true });
    const output = JSON.stringify(result);
    expect(output).not.toContain("staff_code");
    for (const record of records) {
      expect(output).not.toContain(record.staff_code);
      expect(output).not.toContain(deriveTemporaryPassword(record.staff_code));
    }
    expect(output).not.toContain(["sb", "secret", "synthetic"].join("_"));
  });

  it("stops after a partial runtime failure and retains the burner input", async () => {
    const records = inputs(3);
    const client = statefulAdmin({ failProfileEmail: records[1].email });
    const cleanup = vi.fn(async () => {});
    let failure;
    try {
      await provisionStaffBatch({ admin: client, inputs: records, redirectTo, cleanup });
    } catch (error) {
      failure = error;
    }
    expect(failure).toMatchObject({ code: "BATCH_RUNTIME_FAILED" });
    expect(failure.report.batch).toMatchObject({ requested: 3, provisioned: 1, failed: 1, not_attempted: 1, burner_file_deleted: false });
    expect(client.createUser).toHaveBeenCalledTimes(2);
    expect(cleanup).not.toHaveBeenCalled();
  });
});
