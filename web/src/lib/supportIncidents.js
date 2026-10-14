export const INCIDENT_TYPES = Object.freeze([
  { value: "stuck", label: "I'm stuck" },
  { value: "looks_wrong", label: "Something looks wrong" },
  { value: "error", label: "I got an error" },
  { value: "other", label: "Other" },
]);

const SAFE_CODE = /^[A-Za-z0-9_.:/ -]+$/;
const SENSITIVE = /(?:sb[_]secret_|sb[_]publishable_|bearer\s+|authorization|access[_ -]?token|refresh[_ -]?token|api[_ -]?key|password|token(?:_hash)?=|\/auth\/v1\/verify)/i;

export class SupportIncidentError extends Error {
  constructor(message, fallbackReference = null) {
    super(message);
    this.name = "SupportIncidentError";
    this.fallbackReference = fallbackReference;
  }
}

export function safeText(value, maxLength) {
  const text = String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, maxLength);
  return text && !SENSITIVE.test(text) ? text : null;
}

export function safeErrorCode(value) {
  const text = safeText(value, 160);
  return text && SAFE_CODE.test(text) ? text : null;
}

export function viewportClass(width = window.innerWidth) {
  return width < 600 ? "phone" : width < 1024 ? "tablet" : "desktop";
}

export function userAgentSummary(userAgent = navigator.userAgent) {
  const platform = /Android/i.test(userAgent) ? "Android" : /iPhone|iPad/i.test(userAgent) ? "iOS" : /Windows/i.test(userAgent) ? "Windows" : /Macintosh/i.test(userAgent) ? "macOS" : /Linux/i.test(userAgent) ? "Linux" : "Other OS";
  const browser = /Edg\//.test(userAgent) ? "Edge" : /Chrome\//.test(userAgent) ? "Chrome" : /Firefox\//.test(userAgent) ? "Firefox" : /Safari\//.test(userAgent) ? "Safari" : "Other browser";
  return `${browser} on ${platform}`;
}

export function buildVersion() {
  const script = document.querySelector('script[type="module"][src]')?.getAttribute("src") || "";
  const asset = script.match(/index-([A-Za-z0-9_-]+)\.js/)?.[1];
  return asset ? `teacher-app-${asset}` : "teacher-app-local";
}

export function fallbackJobReference(jobId) {
  return jobId ? `JOB-${String(jobId).replace(/-/g, "").slice(0, 8).toUpperCase()}` : null;
}

export function incidentSnapshot({ user, job = null, currentView, questionContext = null, unresolvedExceptionCount = null, appVersion = buildVersion() }) {
  if (!user?.id) throw new SupportIncidentError("Sign in before sending a report.");
  return {
    user_id: user.id,
    job_id: job?.id || null,
    source_filename: safeText(job?.source_filename, 260),
    current_view: safeText(currentView, 80),
    current_stage: safeText(job?.stage, 120),
    job_status: safeText(job?.status, 80),
    review_required: typeof job?.review_required === "boolean" ? job.review_required : null,
    question_context: safeText(questionContext, 120),
    latest_safe_error: safeErrorCode(job?.error_code),
    unresolved_exception_count: Number.isInteger(unresolvedExceptionCount) && unresolvedExceptionCount >= 0 ? unresolvedExceptionCount : null,
    app_version: safeText(appVersion, 120),
    user_agent_summary: userAgentSummary(),
    viewport_class: viewportClass(),
  };
}

export async function submitSupportIncident({ client, user, incidentType, teacherNote, context }) {
  if (!INCIDENT_TYPES.some(({ value }) => value === incidentType)) throw new SupportIncidentError("Choose what happened before sending the report.");
  const snapshot = incidentSnapshot({ user, ...context });
  const { data, error } = await client.from("support_incidents").insert({
    ...snapshot,
    incident_type: incidentType,
    teacher_note: safeText(teacherNote, 1200),
  }).select("id,reference,status,notification_status").single();
  if (error || !data?.reference) {
    throw new SupportIncidentError("We couldn't send the report.", fallbackJobReference(snapshot.job_id));
  }

  let notification = { error: true, data: null };
  try {
    notification = await client.functions.invoke("notify-support-incident", { body: { incident_id: data.id } });
  } catch {
    // The durable incident already exists; notification is a separate best-effort step.
  }
  return {
    ...data,
    notification_delayed: Boolean(notification.error || notification.data?.notification_status !== "sent"),
  };
}
