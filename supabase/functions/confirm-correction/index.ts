import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") {
      return Response.json({ error: "method_not_allowed" }, { status: 405 });
    }

    let body: Record<string, unknown>;
    try { body = await req.json(); } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }

    const correctionId =
      typeof body.correction_id === "string" && UUID_RE.test(body.correction_id)
        ? body.correction_id
        : null;
    if (!correctionId) {
      return Response.json({ error: "invalid_correction_id" }, { status: 400 });
    }

    const { data: correction, error } = await ctx.supabase
      .from("corrections")
      .select("id,job_id,user_id,exception_id,input_kind,display_text,proposed_patch,confirmation_status")
      .eq("id", correctionId)
      .maybeSingle();

    if (error) return Response.json({ error: "correction_lookup_failed" }, { status: 502 });
    if (!correction) return Response.json({ error: "correction_not_found" }, { status: 404 });
    if (correction.confirmation_status !== "pending") {
      return Response.json(
        { error: "correction_not_pending", status: correction.confirmation_status },
        { status: 409 },
      );
    }
    if (!correction.proposed_patch || !correction.display_text) {
      return Response.json({ error: "reinterpretation_not_ready" }, { status: 409 });
    }

    const { data: exception, error: exError } = await ctx.supabase
      .from("exceptions")
      .select("id,job_id,status")
      .eq("id", correction.exception_id)
      .eq("job_id", correction.job_id)
      .maybeSingle();

    if (exError) return Response.json({ error: "exception_lookup_failed" }, { status: 502 });
    if (!exception || exception.status !== "awaiting_confirmation") {
      return Response.json({ error: "exception_not_confirmable" }, { status: 409 });
    }

    const now = new Date().toISOString();

    const { error: correctionError } = await ctx.supabaseAdmin
      .from("corrections")
      .update({
        confirmation_status: "confirmed",
        confirmed_at: now,
        updated_at: now,
      })
      .eq("id", correctionId)
      .eq("confirmation_status", "pending");

    if (correctionError) {
      return Response.json({ error: "confirmation_failed" }, { status: 502 });
    }

    const { error: exceptionError } = await ctx.supabaseAdmin
      .from("exceptions")
      .update({
        status: "resolved",
        resolved_by_correction_id: correctionId,
        updated_at: now,
      })
      .eq("id", correction.exception_id)
      .eq("status", "awaiting_confirmation");

    if (exceptionError) {
      return Response.json({ error: "exception_resolution_failed" }, { status: 502 });
    }

    const { count, error: countError } = await ctx.supabaseAdmin
      .from("exceptions")
      .select("id", { count: "exact", head: true })
      .eq("job_id", correction.job_id)
      .in("status", ["open", "awaiting_reinterpretation", "awaiting_confirmation"]);

    if (countError) return Response.json({ error: "review_count_failed" }, { status: 502 });

    const remaining = Number(count ?? 0);
    const nextStatus = remaining === 0 ? "correction_confirmed" : "needs_review";
    const nextStage = remaining === 0 ? "phase7_correction_confirmed" : "phase7_review";

    await ctx.supabaseAdmin.from("jobs").update({
      status: nextStatus,
      stage: nextStage,
      review_required: remaining > 0,
      updated_at: now,
    }).eq("id", correction.job_id);

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: correction.job_id,
      user_id: correction.user_id,
      event_type: "phase7_correction_confirmed",
      stage: nextStage,
      payload: {
        correction_id: correctionId,
        exception_id: correction.exception_id,
        remaining_review_count: remaining,
      },
    });

    return Response.json({
      ok: true,
      correction_id: correctionId,
      remaining_review_count: remaining,
      job_status: nextStatus,
      job_stage: nextStage,
    });
  }),
};