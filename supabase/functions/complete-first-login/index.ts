import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const PASSWORD_MINIMUM = 12;

function acceptablePassword(value: unknown): value is string {
  return typeof value === "string"
    && value.length >= PASSWORD_MINIMUM
    && /[a-z]/.test(value)
    && /[A-Z]/.test(value)
    && /[0-9]/.test(value)
    && /[^A-Za-z0-9]/.test(value);
}

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") {
      return Response.json({ error: "method_not_allowed" }, { status: 405 });
    }

    let password: unknown;
    try {
      password = (await req.json())?.password;
    } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }
    if (!acceptablePassword(password)) {
      return Response.json({ error: "password_requirements_not_met" }, { status: 400 });
    }

    const { data: identity, error: identityError } = await ctx.supabase.auth.getUser();
    if (identityError || !identity.user?.id) {
      return Response.json({ error: "authentication_required" }, { status: 401 });
    }

    const { data: profile, error: profileError } = await ctx.supabaseAdmin
      .from("department_profiles")
      .select("user_id,active,must_change_password")
      .eq("user_id", identity.user.id)
      .maybeSingle();
    if (profileError) {
      return Response.json({ error: "profile_lookup_failed" }, { status: 502 });
    }
    if (!profile?.active || profile.must_change_password !== true) {
      return Response.json({ error: "password_change_not_available" }, { status: 403 });
    }

    // Forward the already verified caller session to Supabase Auth's documented
    // user-update endpoint. The password is never logged or stored in an
    // application table.
    const authorization = req.headers.get("authorization") || "";
    const publishableKey = req.headers.get("apikey") || "";
    const projectUrl = Deno.env.get("SUPABASE_URL") || "";
    if (!authorization.startsWith("Bearer ") || !publishableKey.startsWith("sb_publishable_") || !projectUrl) {
      return Response.json({ error: "authentication_required" }, { status: 401 });
    }
    const passwordResponse = await fetch(`${projectUrl}/auth/v1/user`, {
      method: "PUT",
      headers: {
        Authorization: authorization,
        apikey: publishableKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ password }),
    });
    if (!passwordResponse.ok) {
      return Response.json({ error: "password_update_failed" }, { status: 400 });
    }

    const { data: completed, error: completionError } = await ctx.supabaseAdmin
      .rpc("pbhs_complete_initial_password_change", { p_user_id: identity.user.id });
    if (completionError || completed !== true) {
      // Fail closed. The password has changed, but normal application access
      // remains blocked until the trusted completion step succeeds on retry.
      return Response.json({ error: "onboarding_completion_failed" }, { status: 502 });
    }

    await fetch(`${projectUrl}/auth/v1/logout?scope=global`, {
      method: "POST",
      headers: { Authorization: authorization, apikey: publishableKey },
    });
    return Response.json({ ok: true, sign_in_required: true });
  }),
};
