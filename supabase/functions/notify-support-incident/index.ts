import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function configuredEmail() {
  const provider = Deno.env.get("SUPPORT_EMAIL_PROVIDER");
  const apiKey = Deno.env.get("RESEND_API_KEY");
  const from = Deno.env.get("SUPPORT_EMAIL_FROM");
  const to = Deno.env.get("SUPPORT_EMAIL_TO");
  return provider === "resend" && apiKey && from && to ? { apiKey, from, to } : null;
}

function line(label: string, value: unknown) {
  return `${label}: ${value == null || value === "" ? "Not available" : String(value)}`;
}

export function supportEmailText(incident: Record<string, unknown>, teacher: Record<string, unknown> | null) {
  return [
    "A teacher submitted a PBHS Memo Converter support report.",
    "",
    line("Reference", incident.reference),
    line("Submitted", incident.created_at),
    line("Teacher", teacher?.display_name),
    line("Teacher email", teacher?.email),
    line("Type", incident.incident_type),
    line("Note", incident.teacher_note),
    line("Job", incident.job_id),
    line("Source file", incident.source_filename),
    line("View", incident.current_view),
    line("Stage", incident.current_stage),
    line("Job status", incident.job_status),
    line("Question", incident.question_context),
    line("Safe error code", incident.latest_safe_error),
    line("Unresolved reviews", incident.unresolved_exception_count),
    line("App version", incident.app_version),
    line("Browser", incident.user_agent_summary),
    line("Viewport", incident.viewport_class),
    "",
    "Investigate this reference with trusted Supabase tooling and follow the documented support procedure.",
    "Memo content, credentials and session material are deliberately excluded.",
  ].join("\n");
}

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") return Response.json({ error: "method_not_allowed" }, { status: 405 });
    let incidentId = "";
    try {
      incidentId = (await req.json())?.incident_id ?? "";
    } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }
    if (!UUID_RE.test(incidentId)) return Response.json({ error: "invalid_incident_id" }, { status: 400 });

    const { data: incident, error } = await ctx.supabase.from("support_incidents")
      .select("id,reference,created_at,user_id,job_id,source_filename,incident_type,teacher_note,current_view,current_stage,job_status,question_context,latest_safe_error,unresolved_exception_count,app_version,user_agent_summary,viewport_class,notification_status")
      .eq("id", incidentId).maybeSingle();
    if (error) return Response.json({ error: "incident_lookup_failed" }, { status: 502 });
    if (!incident) return Response.json({ error: "incident_not_found" }, { status: 404 });
    if (incident.notification_status === "sent") return Response.json({ reference: incident.reference, notification_status: "sent" });

    const email = configuredEmail();
    if (!email) {
      await ctx.supabaseAdmin.from("support_incidents").update({
        notification_status: "unavailable", notification_last_error: "email_provider_not_configured",
      }).eq("id", incident.id);
      return Response.json({ reference: incident.reference, notification_status: "unavailable" }, { status: 202 });
    }

    const { data: teacher } = await ctx.supabaseAdmin.from("department_profiles")
      .select("display_name,email").eq("user_id", incident.user_id).maybeSingle();
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${email.apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: email.from,
        to: [email.to],
        subject: `[${incident.reference}] PBHS Memo Converter support report`,
        text: supportEmailText(incident, teacher),
      }),
    });
    if (!response.ok) {
      await ctx.supabaseAdmin.from("support_incidents").update({
        notification_status: "failed", notification_last_error: `email_provider_http_${response.status}`,
      }).eq("id", incident.id);
      return Response.json({ reference: incident.reference, notification_status: "failed" }, { status: 202 });
    }
    await ctx.supabaseAdmin.from("support_incidents").update({
      notification_status: "sent", notification_last_error: null,
    }).eq("id", incident.id);
    return Response.json({ reference: incident.reference, notification_status: "sent" });
  }),
};
