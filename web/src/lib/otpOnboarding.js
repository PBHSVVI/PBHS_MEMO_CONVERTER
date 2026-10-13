export const SETUP_PROFILE_MESSAGE =
  "Your PBHS Mathematics account has not been activated. Please contact the Mathematics Department administrator.";

export function normalizeSetupEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export async function requestSetupCode(client, email) {
  return client.auth.signInWithOtp({
    email: normalizeSetupEmail(email),
    options: { shouldCreateUser: false },
  });
}

export async function verifySetupCode(client, email, token) {
  return client.auth.verifyOtp({
    email: normalizeSetupEmail(email),
    token: String(token || "").replace(/\s/g, ""),
    type: "email",
  });
}

export async function activeSetupProfile(client) {
  const { data, error } = await client.rpc("pbhs_active_profile_status");
  return { active: error == null && data === true, error };
}
