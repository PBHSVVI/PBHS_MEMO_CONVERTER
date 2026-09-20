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
      .select("id,job_id,user_id,exception_id,confirmation_status")
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

    const now = new Date().toISOString();

    await ctx.supabaseAdmin.from("corrections").update({
      confirmation_status: "rejected",
      updated_at: now,
    }).eq("id", correctionId).eq("confirmation_status", "pending");

    await ctx.supabaseAdmin.from("exceptions").update({
      status: "open",
      resolved_by_correction_id: null,
      updated_at: now,
    }).eq("id", correction.exception_id)
      .in("status", ["awaiting_reinterpretation", "awaiting_confirmation"]);

    await ctx.supabaseAdmin.from("jobs").update({
      status: "needs_review",
      stage: "phase7_review",
      review_required: true,
      updated_at: now,
    }).eq("id", correction.job_id).eq("status", "correction_pending");

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: correction.job_id,
      user_id: correction.user_id,
      event_type: "phase7_correction_rejected",
      stage: "phase7_review",
      payload: {
        correction_id: correctionId,
        exception_id: correction.exception_id,
      },
    });

    return Response.json({
      ok: true,
      correction_id: correctionId,
      job_status: "needs_review",
    });
  }),
};