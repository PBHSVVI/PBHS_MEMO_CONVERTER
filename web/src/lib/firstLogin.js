export const FIRST_LOGIN = Object.freeze({
  READY: "ready",
  PASSWORD_CHANGE_REQUIRED: "password_change_required",
  UNAVAILABLE: "unavailable",
});

export async function firstLoginStatus(client) {
  const { data, error } = await client.rpc("pbhs_first_login_status");
  if (error || !Object.values(FIRST_LOGIN).includes(data)) {
    return { status: FIRST_LOGIN.UNAVAILABLE, error: error || new Error("Invalid first-login status") };
  }
  return { status: data, error: null };
}

export async function completeFirstLogin(client, password) {
  return client.functions.invoke("complete-first-login", { body: { password } });
}
