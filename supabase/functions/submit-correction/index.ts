import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const KINDS = new Set(["suggestion", "typed", "photo", "upload"]);

function asUuid(value: unknown): string | null {
  return typeof value === "string" && UUID_RE.test(value) ? value : null;
}

function displaySuggestion(value: unknown): string {
  if (!value || typeof value !== "object") return "Use suggested interpretation";
  const item = value as Record<string, unknown>;
  for (const key of ["candidate", "value", "display_text", "text"]) {
    const v = item[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "Use suggested interpretation";
}

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") {
      return Response.json({ error: "method_not_allowed" }, { status: 405 });
    }

    let body: Record<string, unknown>;
    try {
      body = await req.json();
    } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }

    const jobId = asUuid(body.job_id);
    const exceptionId = asUuid(body.exception_id);
    const correctionId = asUuid(body.correction_id) ?? crypto.randomUUID();
    const inputKind = typeof body.input_kind === "string" ? body.input_kind : "";

    if (!jobId || !exceptionId || !KINDS.has(inputKind)) {
      return Response.json({ error: "invalid_request" }, { status: 400 });
    }

    const { data: job, error: jobError } = await ctx.supabase
      .from("jobs")
      .select("id,user_id,status,stage")
      .eq("id", jobId)
      .maybeSingle();

    if (jobError) return Response.json({ error: "job_lookup_failed" }, { status: 502 });
    if (!job) return Response.json({ error: "job_not_found" }, { status: 404 });
    if (!["needs_review", "correction_pending"].includes(job.status)) {
      return Response.json({ error: "job_not_reviewable", status: job.status }, { status: 409 });
    }

    const { data: exception, error: exceptionError } = await ctx.supabase
      .from("exceptions")
      .select("id,job_id,user_id,level,category,affected_id,message,suggestions,status")
      .eq("id", exceptionId)
      .eq("job_id", jobId)
      .maybeSingle();

    if (exceptionError) return Response.json({ error: "exception_lookup_failed" }, { status: 502 });
    if (!exception) return Response.json({ error: "exception_not_found" }, { status: 404 });
    if (exception.status === "resolved") {
      return Response.json({ error: "exception_already_resolved" }, { status: 409 });
    }

    const { data: active } = await ctx.supabase
      .from("corrections")
      .select("id")
      .eq("exception_id", exceptionId)
      .eq("confirmation_status", "pending")
      .limit(1);
    if (active && active.length) {
      return Response.json(
        { error: "pending_correction_exists", correction_id: active[0].id },
        { status: 409 },
      );
    }

    let typedText: string | null = null;
    let storagePath: string | null = null;
    let displayText: string | null = null;
    let proposedPatch: Record<string, unknown> | null = null;
    let exceptionStatus = "awaiting_reinterpretation";

    if (inputKind === "suggestion") {
      const suggestions = Array.isArray(exception.suggestions) ? exception.suggestions : [];
      const index = Number(body.suggestion_index);
      if (!Number.isInteger(index) || index < 0 || index >= suggestions.length) {
        return Response.json({ error: "invalid_suggestion_index" }, { status: 400 });
      }
      const selected = suggestions[index];
      displayText = displaySuggestion(selected);
      proposedPatch = {
        schema_version: "1.0",
        operation: "accept_suggestion",
        category: exception.category,
        affected_id: exception.affected_id,
        suggestion: selected,
      };
      exceptionStatus = "awaiting_confirmation";
    } else if (inputKind === "typed") {
      typedText = typeof body.typed_text === "string" ? body.typed_text.trim() : "";
      if (!typedText || typedText.length > 4000) {
        return Response.json({ error: "invalid_typed_text" }, { status: 400 });
      }
      displayText = typedText;
      proposedPatch = {
        schema_version: "1.0",
        operation: "teacher_text_override",
        category: exception.category,
        affected_id: exception.affected_id,
        text: typedText,
      };
      exceptionStatus = "awaiting_confirmation";
    } else {
      storagePath = typeof body.storage_path === "string" ? body.storage_path : "";
      const expectedPrefix = `${job.user_id}/${jobId}/corrections/${correctionId}/`;
      if (!storagePath.startsWith(expectedPrefix) || storagePath.length > 700) {
        return Response.json({ error: "invalid_storage_path" }, { status: 400 });
      }
      const { error: downloadError } = await ctx.supabaseAdmin.storage
        .from("memo-files")
        .download(storagePath);
      if (downloadError) {
        return Response.json({ error: "correction_file_not_found" }, { status: 400 });
      }
      displayText = inputKind === "photo"
        ? "New correction photograph received; reinterpretation required."
        : "New correction file received; reinterpretation required.";
    }

    const now = new Date().toISOString();
    const { data: correction, error: insertError } = await ctx.supabaseAdmin
      .from("corrections")
      .insert({
        id: correctionId,
        job_id: jobId,
        user_id: job.user_id,
        exception_id: exceptionId,
        input_kind: inputKind,
        typed_text: typedText,
        storage_path: storagePath,
        display_text: displayText,
        proposed_patch: proposedPatch,
        confirmation_status: "pending",
        updated_at: now,
      })
      .select("id,job_id,exception_id,input_kind,display_text,proposed_patch,confirmation_status,created_at")
      .single();

    if (insertError) {
      console.error("correction insert failed", insertError.code);
      return Response.json({ error: "correction_insert_failed" }, { status: 502 });
    }

    const { error: exUpdateError } = await ctx.supabaseAdmin
      .from("exceptions")
      .update({ status: exceptionStatus, updated_at: now })
      .eq("id", exceptionId)
      .eq("job_id", jobId);
    if (exUpdateError) {
      return Response.json({ error: "exception_transition_failed" }, { status: 502 });
    }

    const { error: jobUpdateError } = await ctx.supabaseAdmin
      .from("jobs")
      .update({
        status: "correction_pending",
        stage: exceptionStatus === "awaiting_confirmation"
          ? "phase7_awaiting_confirmation"
          : "phase7_awaiting_reinterpretation",
        review_required: true,
        updated_at: now,
      })
      .eq("id", jobId)
      .in("status", ["needs_review", "correction_pending"]);
    if (jobUpdateError) {
      return Response.json({ error: "job_transition_failed" }, { status: 502 });
    }

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: jobId,
      user_id: job.user_id,
      event_type: "phase7_correction_submitted",
      stage: exceptionStatus,
      payload: {
        correction_id: correctionId,
        exception_id: exceptionId,
        input_kind: inputKind,
        confirmation_ready: proposedPatch !== null,
      },
    });

    return Response.json({
      ok: true,
      correction,
      exception_status: exceptionStatus,
      confirmation_ready: proposedPatch !== null,
    }, { status: 201 });
  }),
};