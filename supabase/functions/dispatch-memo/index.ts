import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";
import {
  metadataDispatchPolicy,
  normalizeTeacherMetadata,
  TeacherMetadataError,
  type TeacherMetadata,
} from "../_shared/teacher-metadata.ts";

function isUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") {
      return Response.json({ error: "method_not_allowed" }, { status: 405 });
    }

    let body: { job_id?: string; teacher_metadata?: unknown };
    try {
      body = await req.json();
    } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }
    if (!isUuid(body.job_id)) {
      return Response.json({ error: "invalid_job_id" }, { status: 400 });
    }

    const hasMetadata = Object.prototype.hasOwnProperty.call(body, "teacher_metadata");
    let normalizedMetadata: TeacherMetadata | null = null;
    if (hasMetadata) {
      try {
        normalizedMetadata = normalizeTeacherMetadata(body.teacher_metadata);
      } catch (error) {
        const detail = error instanceof TeacherMetadataError ? error.code : "invalid_payload";
        return Response.json(
          { error: "invalid_teacher_metadata", detail },
          { status: 400 },
        );
      }
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
      .select("id,user_id,status,stage,attempt_count,teacher_metadata,teacher_metadata_revision,teacher_metadata_updated_at,dispatched_at,error_code,error_message")
      .eq("id", jobId)
      .maybeSingle();
    if (lookupError) {
      console.error("job lookup failed", lookupError.code);
      return Response.json({ error: "job_lookup_failed" }, { status: 502 });
    }
    if (!visibleJob) {
      return Response.json({ error: "job_not_found" }, { status: 404 });
    }

    const policy = metadataDispatchPolicy(visibleJob, hasMetadata);
    if (!policy.allowed) {
      return Response.json(
        { error: policy.error, status: visibleJob.status, stage: visibleJob.stage },
        { status: 409 },
      );
    }

    const claimedFromStatus = visibleJob.status;
    const claimedFromStage = visibleJob.stage;
    const now = new Date().toISOString();
    const nextRevision = Number(visibleJob.teacher_metadata_revision ?? 0) +
      (hasMetadata ? 1 : 0);
    const claimValues: Record<string, unknown> = {
      status: "dispatched",
      stage: "dispatch",
      attempt_count: Number(visibleJob.attempt_count ?? 0) + 1,
      dispatched_at: now,
      updated_at: now,
      error_code: null,
      error_message: null,
    };
    if (hasMetadata) {
      claimValues.teacher_metadata = normalizedMetadata;
      claimValues.teacher_metadata_revision = nextRevision;
      claimValues.teacher_metadata_updated_at = now;
    }

    const { data: claimedJob, error: claimError } = await ctx.supabaseAdmin
      .from("jobs")
      .update(claimValues)
      .eq("id", jobId)
      .eq("status", claimedFromStatus)
      .eq("stage", claimedFromStage)
      .select("id,user_id")
      .maybeSingle();
    if (claimError) {
      console.error("dispatch claim failed", claimError.code);
      return Response.json({ error: "dispatch_claim_failed" }, { status: 502 });
    }
    if (!claimedJob) {
      return Response.json({ error: "job_already_claimed" }, { status: 409 });
    }

    if (hasMetadata && normalizedMetadata) {
      const { error: metadataEventError } = await ctx.supabaseAdmin
        .from("job_events")
        .insert({
          job_id: jobId,
          user_id: claimedJob.user_id,
          event_type: "teacher_metadata_submitted",
          stage: policy.mode === "review_resume"
            ? "phase8_1b_metadata_review"
            : "upload",
          payload: {
            revision: nextRevision,
            values: normalizedMetadata.values,
            confirmed_absent: normalizedMetadata.confirmed_absent,
          },
        });
      if (metadataEventError) {
        await ctx.supabaseAdmin
          .from("jobs")
          .update({
            status: claimedFromStatus,
            stage: claimedFromStage,
            attempt_count: Number(visibleJob.attempt_count ?? 0),
            teacher_metadata: visibleJob.teacher_metadata,
            teacher_metadata_revision: Number(
              visibleJob.teacher_metadata_revision ?? 0,
            ),
            teacher_metadata_updated_at: visibleJob.teacher_metadata_updated_at,
            dispatched_at: visibleJob.dispatched_at,
            error_code: visibleJob.error_code,
            error_message: visibleJob.error_message,
            updated_at: now,
          })
          .eq("id", jobId)
          .eq("status", "dispatched");
        console.error("teacher metadata audit failed", metadataEventError.code);
        return Response.json(
          { error: "teacher_metadata_audit_failed" },
          { status: 502 },
        );
      }
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
      const restoredStage = claimedFromStatus === "needs_review"
        ? claimedFromStage
        : claimedFromStatus === "queued"
        ? "dispatch_retry"
        : "dispatch_retry_failed";
      await ctx.supabaseAdmin
        .from("jobs")
        .update({
          status: claimedFromStatus,
          stage: restoredStage,
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
        stage: claimedFromStage,
        payload: {
          github_http_status: dispatch.status,
          teacher_metadata_retained: hasMetadata,
          teacher_metadata_revision: nextRevision,
        },
      });
      console.error("github dispatch failed", dispatch.status);
      return Response.json({ error: "github_dispatch_failed" }, { status: 502 });
    }

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: jobId,
      user_id: claimedJob.user_id,
      event_type: "dispatched",
      stage: "dispatch",
      payload: {
        repository: githubRepository,
        ref: githubRef,
        dispatch_mode: policy.mode,
        teacher_metadata_revision: nextRevision,
      },
    });

    return Response.json(
      {
        ok: true,
        job_id: jobId,
        status: "dispatched",
        teacher_metadata_revision: nextRevision,
      },
      { status: 202 },
    );
  }),
};
