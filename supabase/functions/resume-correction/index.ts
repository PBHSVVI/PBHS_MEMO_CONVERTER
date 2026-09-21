import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") return Response.json({ error: "method_not_allowed" }, { status: 405 });
    let body: { job_id?: string };
    try { body = await req.json(); }
    catch { return Response.json({ error: "invalid_json" }, { status: 400 }); }

    const jobId = typeof body.job_id === "string" && UUID_RE.test(body.job_id) ? body.job_id : null;
    if (!jobId) return Response.json({ error: "invalid_job_id" }, { status: 400 });

    const { data: job, error: jobError } = await ctx.supabase
      .from("jobs").select("id,user_id,status,attempt_count").eq("id", jobId).maybeSingle();
    if (jobError) return Response.json({ error: "job_lookup_failed" }, { status: 502 });
    if (!job) return Response.json({ error: "job_not_found" }, { status: 404 });
    if (!["needs_review", "correction_confirmed"].includes(job.status)) {
      return Response.json({ error: "job_not_resumable", status: job.status }, { status: 409 });
    }

    const { data: pending, error: correctionError } = await ctx.supabase
      .from("corrections").select("id")
      .eq("job_id", jobId).eq("confirmation_status", "confirmed").is("applied_at", null).limit(1);
    if (correctionError) return Response.json({ error: "correction_lookup_failed" }, { status: 502 });
    if (!pending?.length) return Response.json({ error: "no_unapplied_confirmed_correction" }, { status: 409 });

    const token = Deno.env.get("GITHUB_TOKEN");
    const repository = Deno.env.get("GITHUB_REPOSITORY") ?? "PBHSVVI/PBHS_MEMO_CONVERTER";
    const ref = Deno.env.get("GITHUB_REF") ?? "main";
    if (!token) return Response.json({ error: "server_not_configured" }, { status: 500 });

    const now = new Date().toISOString();
    if (job.status === "needs_review") {
      const { error: markError } = await ctx.supabaseAdmin.from("jobs").update({
        status: "correction_confirmed", stage: "phase7_correction_confirmed",
        updated_at: now, error_code: null, error_message: null,
      }).eq("id", jobId).eq("status", "needs_review");
      if (markError) return Response.json({ error: "job_transition_failed" }, { status: 502 });
    }

    const { data: claimed, error: claimError } = await ctx.supabaseAdmin.from("jobs").update({
      status: "dispatched", stage: "phase7_redispatch",
      attempt_count: Number(job.attempt_count ?? 0) + 1,
      dispatched_at: now, updated_at: now,
      error_code: null, error_message: null,
    }).eq("id", jobId).eq("status", "correction_confirmed").select("id").maybeSingle();
    if (claimError || !claimed) return Response.json({ error: "dispatch_claim_failed" }, { status: 409 });

    const response = await fetch(
      `https://api.github.com/repos/${repository}/actions/workflows/process-memo.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "PBHS-Memo-Converter-Phase7",
        },
        body: JSON.stringify({ ref, inputs: { job_id: jobId } }),
      },
    );

    if (!response.ok) {
      await ctx.supabaseAdmin.from("jobs").update({
        status: "correction_confirmed", stage: "phase7_dispatch_retry",
        error_code: "GITHUB_DISPATCH_FAILED",
        error_message: `GitHub workflow dispatch returned HTTP ${response.status}`,
        updated_at: new Date().toISOString(),
      }).eq("id", jobId).eq("status", "dispatched");
      return Response.json({ error: "github_dispatch_failed" }, { status: 502 });
    }

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: jobId, user_id: job.user_id,
      event_type: "phase7_redispatched", stage: "phase7_redispatch",
      payload: { repository, ref, reason: "confirmed_correction_overlay" },
    });

    return Response.json({ ok: true, job_id: jobId, status: "dispatched" }, { status: 202 });
  }),
};
