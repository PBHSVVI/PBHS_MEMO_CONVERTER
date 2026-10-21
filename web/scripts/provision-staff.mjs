#!/usr/bin/env node
import { access, readFile, unlink } from "node:fs/promises";
import process from "node:process";
import {
  ProvisioningError,
  createSupabaseAdmin,
  parseProvisioningCsv,
  provisionStaff,
  provisionStaffBatch,
  redactSensitiveValue,
  safeProvisioningReport,
  selectTrustedCredential,
  validateInviteRedirect,
  validateStaffRecord,
} from "./staffProvisioning.mjs";

function argumentsFrom(argv) {
  const values = {};
  const flags = new Set();
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) throw new Error(`Unexpected argument: ${value}`);
    if (["--dry-run", "--reissue-invite", "--repair-profile", "--update-profile", "--temporary-password", "--batch"].includes(value)) flags.add(value);
    else values[value] = argv[++index];
  }
  return { values, flags };
}

async function loadInput(values, batch) {
  if (!values["--input"]) {
    return { email: values["--email"], display_name: values["--display-name"], role: values["--role"], hod_scope: values["--hod-scope"], staff_code: values["--staff-code"] };
  }
  const source = values["--input"] === "-"
    ? await new Promise((resolve, reject) => {
      let data = ""; process.stdin.setEncoding("utf8"); process.stdin.on("data", (chunk) => { data += chunk; });
      process.stdin.on("end", () => resolve(data)); process.stdin.on("error", reject);
    })
    : await readFile(values["--input"], "utf8");
  const trimmed = source.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    const parsed = JSON.parse(trimmed);
    if (batch && !Array.isArray(parsed)) throw new ProvisioningError("BATCH_ARRAY_REQUIRED", "Batch JSON input must be an array.");
    if (!batch && Array.isArray(parsed)) throw new ProvisioningError("SINGLE_RECORD_REQUIRED", "Single-record JSON input must be one object.");
    return parsed;
  }
  const rows = parseProvisioningCsv(trimmed, { batch });
  return batch ? rows : rows[0];
}

function projectRefFromUrl(url) {
  const match = String(url || "").match(/^https:\/\/([a-z0-9-]+)\.supabase\.co\/?$/i);
  return match?.[1] || null;
}

async function main() {
  const { values, flags } = argumentsFrom(process.argv.slice(2));
  const batch = flags.has("--batch");
  if (batch && (!values["--input"] || values["--input"] === "-")) {
    throw new ProvisioningError("PRIVATE_BATCH_FILE_REQUIRED", "Batch mode requires a named private input file so successful cleanup can be verified.");
  }
  if (batch && ["--reissue-invite", "--repair-profile", "--update-profile"].some((flag) => flags.has(flag))) {
    throw new ProvisioningError("UNSAFE_BATCH_OPTION", "Batch onboarding does not permit invite reissue, profile repair, or profile update options.");
  }
  const rawInput = await loadInput(values, batch);
  const temporaryMode = flags.has("--temporary-password");
  if (batch) {
    if (!temporaryMode) throw new ProvisioningError("TEMPORARY_PASSWORD_REQUIRED", "Batch onboarding requires --temporary-password.");
    const redirectTo = validateInviteRedirect(values["--redirect-to"] || process.env.PBHS_INVITE_REDIRECT || "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=setup");
    const url = process.env.SUPABASE_URL;
    const projectRef = projectRefFromUrl(url);
    if (!projectRef) throw new ProvisioningError("INVALID_SUPABASE_URL", "Set SUPABASE_URL to the exact target project URL.");
    const expectedProjectRef = String(process.env.PBHS_PROVISIONING_PROJECT_REF || "").trim();
    if (!expectedProjectRef || projectRef !== expectedProjectRef) {
      throw new ProvisioningError("PROJECT_REF_MISMATCH", "SUPABASE_URL does not match PBHS_PROVISIONING_PROJECT_REF.");
    }
    const credential = selectTrustedCredential(process.env);
    if (credential.deprecated) {
      process.stderr.write("Warning: SUPABASE_SERVICE_ROLE_KEY is deprecated; use SUPABASE_SECRET_KEY with a modern Supabase secret key.\n");
    }
    const admin = createSupabaseAdmin({ url, secret: credential.secret });
    const result = await provisionStaffBatch({
      admin,
      inputs: rawInput,
      redirectTo,
      dryRun: flags.has("--dry-run"),
      cleanup: flags.has("--dry-run") ? null : async () => {
        await unlink(values["--input"]);
        try {
          await access(values["--input"]);
          throw new ProvisioningError("BURNER_FILE_CLEANUP_FAILED", "The private batch input still exists after cleanup.");
        } catch (error) {
          if (error?.code !== "ENOENT") throw error;
        }
      },
    });
    console.log(JSON.stringify(redactSensitiveValue({ project_ref: projectRef, ...result }), null, 2));
    return;
  }
  const input = validateStaffRecord(rawInput);
  const staffCode = rawInput?.staff_code == null || rawInput.staff_code === "" ? null : String(rawInput.staff_code).trim();
  if (temporaryMode !== Boolean(staffCode)) {
    throw new ProvisioningError(
      "TEMPORARY_PASSWORD_INPUT_MISMATCH",
      "Use --temporary-password together with exactly one runtime staff_code value.",
    );
  }
  const redirectTo = validateInviteRedirect(values["--redirect-to"] || process.env.PBHS_INVITE_REDIRECT || "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=setup");
  const url = process.env.SUPABASE_URL;
  const credentialAvailable = Boolean(process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY);
  if (flags.has("--dry-run") && (!url || !credentialAvailable)) {
    console.log(JSON.stringify({ ...safeProvisioningReport({ record: input, state: "offline_validated", planned: ["existing_state_not_checked"] }, true, temporaryMode), redirect: redirectTo }, null, 2));
    return;
  }
  const credential = selectTrustedCredential(process.env);
  if (credential.deprecated) {
    process.stderr.write("Warning: SUPABASE_SERVICE_ROLE_KEY is deprecated; use SUPABASE_SECRET_KEY with a modern Supabase secret key.\n");
  }
  const secret = credential.secret;
  const admin = createSupabaseAdmin({ url, secret });
  const result = await provisionStaff({
    admin, input, redirectTo, dryRun: flags.has("--dry-run"),
    reissueInvite: flags.has("--reissue-invite"), repairProfile: flags.has("--repair-profile"), updateProfile: flags.has("--update-profile"),
    staffCode,
    temporaryPasswordRecovery: temporaryMode,
  });
  console.log(JSON.stringify(redactSensitiveValue(result), null, 2));
}

main().catch((error) => {
  const safe = error instanceof ProvisioningError
    ? { error: error.code, message: error.message, action: error.action, ...(error.report ? { report: error.report } : {}) }
    : { error: "PROVISIONING_FAILED", message: "Provisioning stopped safely." };
  console.error(JSON.stringify(redactSensitiveValue(safe), null, 2));
  process.exitCode = 1;
});
