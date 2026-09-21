import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function dispatchJob(ctx: any, jobId: string, userId: string, attemptCount: number) {
  const token = Deno.env.get("GITHUB_TOKEN");
  const repository = Deno.env.get("GITHUB_REPOSITORY") ?? "PBHSVVI/PBHS_MEMO_CONVERTER";
  const ref = Deno.env.get("GITHUB_REF") ?? "main";
  if (!token) return { ok: false, status: 500, error: "server_not_configured" };

  const now = new Date().toISOString();
  const { data: claimed, error: claimError } = await ctx.supabaseAdmin
    .from("jobs")
    .update({
      status: "dispatched", stage: "phase7_redispatch",
      attempt_count: Number(attemptCount ?? 0) + 1,
      dispatched_at: now, updated_at: now,
      error_code: null, error_message: null,
    })
    .eq("id", jobId).eq("status", "correction_confirmed")
    .select("id").maybeSingle();
  if (claimError || !claimed) return { ok: false, status: 409, error: "dispatch_claim_failed" };

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
    return { ok: false, status: 502, error: "github_dispatch_failed" };
  }

  await ctx.supabaseAdmin.from("job_events").insert({
    job_id: jobId, user_id: userId,
    event_type: "phase7_redispatched", stage: "phase7_redispatch",
    payload: { repository, ref },
  });
  return { ok: true, status: 202 };
}

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") return Response.json({ error: "method_not_allowed" }, { status: 405 });

    let body: Record<string, unknown>;
    try { body = await req.json(); }
    catch { return Response.json({ error: "invalid_json" }, { status: 400 }); }

    const correctionId = typeof body.correction_id === "string" && UUID_RE.test(body.correction_id)
      ? body.correction_id : null;
    if (!correctionId) return Response.json({ error: "invalid_correction_id" }, { status: 400 });

    const { data: correction, error } = await ctx.supabase
      .from("corrections")
      .select("id,job_id,user_id,exception_id,display_text,proposed_patch,confirmation_status")
      .eq("id", correctionId).maybeSingle();
    if (error) return Response.json({ error: "correction_lookup_failed" }, { status: 502 });
    if (!correction) return Response.json({ error: "correction_not_found" }, { status: 404 });
    if (correction.confirmation_status !== "pending") {
      return Response.json({ error: "correction_not_pending" }, { status: 409 });
    }
    if (!correction.proposed_patch || !correction.display_text) {
      return Response.json({ error: "reinterpretation_not_ready" }, { status: 409 });
    }

    const { data: exception } = await ctx.supabase
      .from("exceptions").select("id,status")
      .eq("id", correction.exception_id).eq("job_id", correction.job_id).maybeSingle();
    if (!exception || exception.status !== "awaiting_confirmation") {
      return Response.json({ error: "exception_not_confirmable" }, { status: 409 });
    }

    const now = new Date().toISOString();
    await ctx.supabaseAdmin.from("corrections").update({
      confirmation_status: "confirmed", confirmed_at: now, updated_at: now,
    }).eq("id", correctionId).eq("confirmation_status", "pending");

    await ctx.supabaseAdmin.from("exceptions").update({
      status: "resolved", resolved_by_correction_id: correctionId, updated_at: now,
    }).eq("id", correction.exception_id).eq("status", "awaiting_confirmation");

    const { count } = await ctx.supabaseAdmin.from("exceptions")
      .select("id", { count: "exact", head: true })
      .eq("job_id", correction.job_id)
      .in("status", ["open", "awaiting_reinterpretation", "awaiting_confirmation"]);
    const remaining = Number(count ?? 0);

    const { data: job, error: jobError } = await ctx.supabaseAdmin.from("jobs")
      .update({
        status: "correction_confirmed", stage: "phase7_correction_confirmed",
        review_required: remaining > 0, updated_at: now,
        error_code: null, error_message: null,
      })
      .eq("id", correction.job_id)
      .in("status", ["correction_pending", "needs_review"])
      .select("id,user_id,attempt_count").maybeSingle();
    if (jobError || !job) return Response.json({ error: "job_transition_failed" }, { status: 502 });

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: correction.job_id, user_id: correction.user_id,
      event_type: "phase7_correction_confirmed", stage: "phase7_correction_confirmed",
      payload: {
        correction_id: correctionId, exception_id: correction.exception_id,
        remaining_review_count: remaining,
      },
    });

    const dispatched = await dispatchJob(
      ctx, correction.job_id, correction.user_id, Number(job.attempt_count ?? 0)
    );
    if (!dispatched.ok) {
      return Response.json({
        error: dispatched.error, correction_id: correctionId,
        confirmed: true, job_status: "correction_confirmed",
      }, { status: dispatched.status });
    }

    return Response.json({
      ok: true, correction_id: correctionId,
      remaining_review_count: remaining,
      job_status: "dispatched", job_stage: "phase7_redispatch",
    }, { status: 202 });
  }),
};
