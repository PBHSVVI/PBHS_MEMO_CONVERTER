import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const KINDS = new Set(["suggestion", "typed", "photo", "upload"]);
const QUESTION_ID_RE = /^\d{1,2}(?:\.\d{1,2}){0,2}$/;
const MARK_CODES = new Set(["M", "A", "CA", "F", "S", "R"]);

function markSemantic(code: string, descriptor: string): string {
  if (code === "CA") return "consistent_accuracy";
  if (code === "M") return "method";
  if (code === "A") return /\b(?:answer|final)\b/i.test(descriptor) ? "answer" : "accuracy";
  if (code === "F") return "formula";
  if (code === "S") return "selection";
  if (code === "R") return "reason";
  return "other";
}

function uuid(value: unknown): string | null {
  return typeof value === "string" && UUID_RE.test(value) ? value : null;
}
function candidateText(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const obj = value as Record<string, unknown>;
  const v = obj.candidate;
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

async function dispatchReinterpretation(
  ctx: any,
  correctionId: string,
  jobId: string,
  userId: string,
): Promise<boolean> {
  const token = Deno.env.get("GITHUB_TOKEN");
  const repository =
    Deno.env.get("GITHUB_REPOSITORY") ?? "PBHSVVI/PBHS_MEMO_CONVERTER";
  const ref = Deno.env.get("GITHUB_REF") ?? "main";

  if (!token) {
    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: jobId, user_id: userId,
      event_type: "phase7_correction_reinterpretation_dispatch_failed",
      stage: "phase7_awaiting_reinterpretation",
      payload: { correction_id: correctionId, reason: "server_not_configured" },
    });
    return false;
  }

  const response = await fetch(
    `https://api.github.com/repos/${repository}/actions/workflows/reinterpret-correction.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "PBHS-Memo-Converter-Phase7",
      },
      body: JSON.stringify({ ref, inputs: { correction_id: correctionId } }),
    },
  );

  const eventType = response.ok
    ? "phase7_correction_reinterpretation_dispatched"
    : "phase7_correction_reinterpretation_dispatch_failed";
  await ctx.supabaseAdmin.from("job_events").insert({
    job_id: jobId, user_id: userId, event_type: eventType,
    stage: "phase7_awaiting_reinterpretation",
    payload: {
      correction_id: correctionId, repository, ref,
      ...(response.ok ? {} : { github_http_status: response.status }),
    },
  });
  return response.ok;
}

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") return Response.json({ error: "method_not_allowed" }, { status: 405 });

    let body: Record<string, unknown>;
    try { body = await req.json(); }
    catch { return Response.json({ error: "invalid_json" }, { status: 400 }); }

    const jobId = uuid(body.job_id);
    const exceptionId = uuid(body.exception_id);
    const correctionId = uuid(body.correction_id) ?? crypto.randomUUID();
    const inputKind = typeof body.input_kind === "string" ? body.input_kind : "";
    if (!jobId || !exceptionId || !KINDS.has(inputKind)) {
      return Response.json({ error: "invalid_request" }, { status: 400 });
    }

    const { data: job, error: jobError } = await ctx.supabase
      .from("jobs").select("id,user_id,status").eq("id", jobId).maybeSingle();
    if (jobError) return Response.json({ error: "job_lookup_failed" }, { status: 502 });
    if (!job) return Response.json({ error: "job_not_found" }, { status: 404 });
    if (!["needs_review", "correction_pending"].includes(job.status)) {
      return Response.json({ error: "job_not_reviewable", status: job.status }, { status: 409 });
    }

    const { data: exception, error: exceptionError } = await ctx.supabase
      .from("exceptions")
      .select("id,job_id,user_id,level,category,affected_id,message,suggestions,status")
      .eq("id", exceptionId).eq("job_id", jobId).maybeSingle();
    if (exceptionError) return Response.json({ error: "exception_lookup_failed" }, { status: 502 });
    if (!exception) return Response.json({ error: "exception_not_found" }, { status: 404 });
    if (exception.status === "resolved" || exception.status === "superseded") {
      return Response.json({ error: "exception_not_active" }, { status: 409 });
    }

    const { data: active } = await ctx.supabase
      .from("corrections").select("id")
      .eq("exception_id", exceptionId).eq("confirmation_status", "pending").limit(1);
    if (active?.length) {
      return Response.json({ error: "pending_correction_exists", correction_id: active[0].id }, { status: 409 });
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
      const selected = suggestions[index] as Record<string, unknown>;
      const candidate = candidateText(selected);
      displayText = candidate ?? "Suggested interpretation selected.";

      if (
        candidate &&
        exception.category === "unlabeled_mark_bearing_question" &&
        selected.kind === "review_numbering"
      ) {
        proposedPatch = {
          schema_version: "1.0",
          operation: "promote_unlabeled_question",
          category: exception.category,
          affected_id: exception.affected_id,
          target_id: candidate,
          suggestion: selected,
        };
        exceptionStatus = "awaiting_confirmation";
      } else if (
        candidate &&
        [
          "numbering_jump",
          "suspicious_question_identifier",
          "scored_major_precedes_subquestions",
        ].includes(exception.category) &&
        selected.kind === "review_numbering"
      ) {
        proposedPatch = {
          schema_version: "1.0",
          operation: "rename_question_identifier",
          category: exception.category,
          affected_id: exception.affected_id,
          target_id: candidate,
          suggestion: selected,
        };
        exceptionStatus = "awaiting_confirmation";
      }
    } else if (inputKind === "typed") {
      typedText = typeof body.typed_text === "string" ? body.typed_text.trim() : "";
      if (!typedText || typedText.length > 4000) {
        return Response.json({ error: "invalid_typed_text" }, { status: 400 });
      }
      displayText = typedText;
      const content = body.content_correction;
      if (content && typeof content === "object") {
        const value = content as Record<string, unknown>;
        const targetId = typeof value.target_id === "string" ? value.target_id.trim() : "";
        const questionText = typeof value.question_text === "string" ? value.question_text.trim() : "";
        const solutionLines = Array.isArray(value.solution_lines)
          ? value.solution_lines.filter((line) => typeof line === "string").map((line) => String(line).trim()).filter(Boolean)
          : [];
        const rawPoints = Array.isArray(value.mark_points) ? value.mark_points : [];
        const markPoints = rawPoints.map((point) => {
          const item = point && typeof point === "object" ? point as Record<string, unknown> : {};
          const code = typeof item.code === "string" ? item.code.toUpperCase() : "";
          const descriptor = typeof item.descriptor === "string" ? item.descriptor.trim() : "";
          return {
            count: Number(item.count),
            code,
            descriptor,
            semantic: markSemantic(code, descriptor),
            source: typeof item.source === "string" ? item.source.trim() : "",
            notation: "teacher_confirmed",
          };
        });
        const invalidTarget = !QUESTION_ID_RE.test(targetId) ||
          (typeof exception.affected_id === "string" && QUESTION_ID_RE.test(exception.affected_id) && targetId !== exception.affected_id);
        const invalidContent = (!questionText && !solutionLines.length) || questionText.length > 2000 ||
          solutionLines.length > 80 || solutionLines.some((line) => line.length > 1000);
        const invalidMarks = markPoints.some((point) =>
          !Number.isInteger(point.count) || point.count < 1 || point.count > 10 ||
          !MARK_CODES.has(point.code) || !point.descriptor || !point.source
        );
        if (invalidTarget || invalidContent || invalidMarks) {
          return Response.json({ error: "invalid_content_correction" }, { status: 400 });
        }
        const conditionalAccuracy = markPoints.length >= 2 && markPoints.every((point) =>
          ["A", "CA"].includes(point.code) && /\bcorrect\b/i.test(point.descriptor)
        );
        const expectedTotal = conditionalAccuracy
          ? Math.max(...markPoints.map((point) => point.count))
          : markPoints.reduce((total, point) => total + point.count, 0);
        proposedPatch = {
          schema_version: "1.0",
          operation: "replace_item_content",
          category: exception.category,
          affected_id: exception.affected_id,
          target_id: targetId,
          question_text: questionText || null,
          solution_lines: solutionLines,
          ...(markPoints.length ? {
            mark_points: markPoints,
            expected_total: expectedTotal,
            mark_calculation_mode: conditionalAccuracy ? "conditional_accuracy" : "additive",
          } : {}),
          reinterpretation_method: "structured_content_editor",
        };
        displayText = `Replace the question or memo content for Question ${targetId}${markPoints.length ? " and use the supplied marking scheme" : ""}.`;
        exceptionStatus = "awaiting_confirmation";
      } else {
        // Ordinary typed text remains evidence and uses the interpretation ladder.
        exceptionStatus = "awaiting_reinterpretation";
      }
    } else {
      storagePath = typeof body.storage_path === "string" ? body.storage_path : "";
      const prefix = `${job.user_id}/${jobId}/corrections/${correctionId}/`;
      if (!storagePath.startsWith(prefix) || storagePath.length > 700) {
        return Response.json({ error: "invalid_storage_path" }, { status: 400 });
      }
      const { error: fileError } = await ctx.supabaseAdmin.storage
        .from("memo-files").download(storagePath);
      if (fileError) return Response.json({ error: "correction_file_not_found" }, { status: 400 });
      displayText = inputKind === "photo"
        ? "New correction photograph received; reinterpretation required."
        : "New correction file received; reinterpretation required.";
    }

    const now = new Date().toISOString();
    const { data: correction, error: insertError } = await ctx.supabaseAdmin
      .from("corrections")
      .insert({
        id: correctionId, job_id: jobId, user_id: job.user_id,
        exception_id: exceptionId, input_kind: inputKind,
        typed_text: typedText, storage_path: storagePath,
        display_text: displayText, proposed_patch: proposedPatch,
        confirmation_status: "pending", updated_at: now,
      })
      .select("id,job_id,exception_id,input_kind,display_text,proposed_patch,confirmation_status,created_at")
      .single();
    if (insertError) {
      console.error("correction insert failed", insertError.code);
      return Response.json({ error: "correction_insert_failed" }, { status: 502 });
    }

    await ctx.supabaseAdmin.from("exceptions").update({
      status: exceptionStatus, updated_at: now,
    }).eq("id", exceptionId).eq("job_id", jobId);

    await ctx.supabaseAdmin.from("jobs").update({
      status: "correction_pending",
      stage: exceptionStatus === "awaiting_confirmation"
        ? "phase7_awaiting_confirmation"
        : "phase7_awaiting_reinterpretation",
      review_required: true, updated_at: now,
    }).eq("id", jobId).in("status", ["needs_review", "correction_pending"]);

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id: jobId, user_id: job.user_id,
      event_type: "phase7_correction_submitted",
      stage: exceptionStatus,
      payload: {
        correction_id: correctionId, exception_id: exceptionId,
        input_kind: inputKind, confirmation_ready: proposedPatch !== null,
      },
    });

    let reinterpretationDispatched: boolean | null = null;
    if (proposedPatch === null) {
      reinterpretationDispatched = await dispatchReinterpretation(
        ctx, correctionId, jobId, job.user_id
      );
    }

    return Response.json({
      ok: true, correction, exception_status: exceptionStatus,
      confirmation_ready: proposedPatch !== null,
      reinterpretation_dispatched: reinterpretationDispatched,
    }, { status: 201 });
  }),
};
