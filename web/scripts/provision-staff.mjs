#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import process from "node:process";
import {
  ProvisioningError,
  createSupabaseAdmin,
  provisionStaff,
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
    if (["--dry-run", "--reissue-invite", "--repair-profile", "--update-profile"].includes(value)) flags.add(value);
    else values[value] = argv[++index];
  }
  return { values, flags };
}

function parseCsv(text) {
  const rows = text.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    const cells = []; let value = ""; let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const char = line[index];
      if (char === '"' && quoted && line[index + 1] === '"') { value += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === "," && !quoted) { cells.push(value); value = ""; }
      else value += char;
    }
    cells.push(value); return cells;
  });
  const headers = rows.shift()?.map((value) => value.trim()) || [];
  if (rows.length !== 1) throw new Error("Provision exactly one staff record per invocation.");
  return Object.fromEntries(headers.map((header, index) => [header, rows[0][index] ?? ""]));
}

async function loadInput(values) {
  if (!values["--input"]) {
    return { email: values["--email"], display_name: values["--display-name"], role: values["--role"], hod_scope: values["--hod-scope"] };
  }
  const source = values["--input"] === "-"
    ? await new Promise((resolve, reject) => {
      let data = ""; process.stdin.setEncoding("utf8"); process.stdin.on("data", (chunk) => { data += chunk; });
      process.stdin.on("end", () => resolve(data)); process.stdin.on("error", reject);
    })
    : await readFile(values["--input"], "utf8");
  const trimmed = source.trim();
  return trimmed.startsWith("{") ? JSON.parse(trimmed) : parseCsv(trimmed);
}

async function main() {
  const { values, flags } = argumentsFrom(process.argv.slice(2));
  const input = validateStaffRecord(await loadInput(values));
  const redirectTo = validateInviteRedirect(values["--redirect-to"] || process.env.PBHS_INVITE_REDIRECT || "https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=setup");
  const url = process.env.SUPABASE_URL;
  const credentialAvailable = Boolean(process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY);
  if (flags.has("--dry-run") && (!url || !credentialAvailable)) {
    console.log(JSON.stringify({ ...safeProvisioningReport({ record: input, state: "offline_validated", planned: ["existing_state_not_checked"] }, true), redirect: redirectTo }, null, 2));
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
  });
  console.log(JSON.stringify(redactSensitiveValue(result), null, 2));
}

main().catch((error) => {
  const safe = error instanceof ProvisioningError
    ? { error: error.code, message: error.message, action: error.action }
    : { error: "PROVISIONING_FAILED", message: "Provisioning stopped safely." };
  console.error(JSON.stringify(redactSensitiveValue(safe), null, 2));
  process.exitCode = 1;
});
