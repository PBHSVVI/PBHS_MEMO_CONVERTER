import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

function isUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") {
      return Response.json({ error: "method_not_allowed" }, { status: 405 });
    }

    let body: { job_id?: string };
    try {
      body = await req.json();
    } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }

    if (!isUuid(body.job_id)) {
      return Response.json({ error: "invalid_job_id" }, { status: 400 });
    }

    const jobId = body.job_id;
    const githubToken = Deno.env.get("GITHUB_TOKEN");
    const githubRepository =
      Deno.env.get("GITHUB_REPOSITORY") ?? "PBHSVVI/PBHS_MEMO_CONVERTER";
    const githubRef = Deno.env.get("GITHUB_REF") ?? "main";

    if (!githubToken) {
      return Response.json(
        { error: "server_not_configured", missing: "GITHUB_TOKEN" },
        { status: 500 },
      );
    }

    const { data: visibleJob, error: lookupError } = await ctx.supabase
      .from("jobs")
      .select("id,user_id,status,attempt_count")
      .eq("id", jobId)
      .maybeSingle();

    if (lookupError) {
      console.error("job lookup failed", lookupError.code);
      return Response.json({ error: "job_lookup_failed" }, { status: 502 });
    }

    if (!visibleJob) {
      return Response.json({ error: "job_not_found" }, { status: 404 });
    }

    if (visibleJob.status !== "queued") {
      return Response.json(
        { error: "job_not_queueable", status: visibleJob.status },
        { status: 409 },
      );
    }

    const now = new Date().toISOString();

    const { data: claimedJob, error: claimError } = await ctx.supabaseAdmin
      .from("jobs")
      .update({
        status: "dispatched",
        stage: "dispatch",
        attempt_count: Number(visibleJob.attempt_count ?? 0) + 1,
        dispatched_at: now,
        updated_at: now,
        error_code: null,
        error_message: null,
      })
      .eq("id", jobId)
      .eq("status", "queued")
      .select("id,user_id")
      .maybeSingle();

    if (claimError) {
      console.error("dispatch claim failed", claimError.code);
      return Response.json({ error: "dispatch_claim_failed" }, { status: 502 });
    }

    if (!claimedJob) {
      return Response.json({ error: "job_already_claimed" }, { status: 409 });
    }

    const dispatch = await fetch(
      `https://api.github.com/repos/${githubRepository}/actions/workflows/process-memo.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${githubToken}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "PBHS-Memo-Converter",
        },
        body: JSON.stringify({
          ref: githubRef,
          inputs: { job_id: jobId },
        }),
      },
    );

    if (!dispatch.ok) {
      const failureTime = new Date().toISOString();

      await ctx.supabaseAdmin
        .from("jobs")
        .update({
          status: "queued",
          stage: "dispatch_retry",
          dispatched_at: null,
          error_code: "GITHUB_DISPATCH_FAILED",
          error_message: `GitHub workflow dispatch returned HTTP ${dispatch.status}`,
          updated_at: failureTime,
        })
        .eq("id", jobId)
        .eq("status", "dispatched");

      await ctx.supabaseAdmin.from("job_events").insert({
        job_id: jobId,
        user_id: claimedJob.user_id,
        event_type: "dispatch_failed",
        stage: "dispatch",
        payload: { github_http_status: dispatch.status },
      });

      console.error("github dispatch failed", dispatch.status);
      return Response.json({ error: "github_dispatch_failed" }, { status: 502 });
    }

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: jobId,
      user_id: claimedJob.user_id,
      event_type: "dispatched",
      stage: "dispatch",
      payload: { repository: githubRepository, ref: githubRef },
    });

    return Response.json(
      { ok: true, job_id: jobId, status: "dispatched" },
      { status: 202 },
    );
  }),
};
