// Phase 0 contract implementation. Not deployed until a dedicated Supabase project exists.
// Platform setting: verify_jwt = true

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const auth = req.headers.get("Authorization");
  if (!auth?.startsWith("Bearer ")) return json({ error: "unauthorized" }, 401);

  const env = Deno.env.toObject();
  const SUPABASE_URL = env.SUPABASE_URL;
  const SUPABASE_PUBLISHABLE_KEY = env.SUPABASE_PUBLISHABLE_KEY;
  const SUPABASE_SECRET_KEY = env.SUPABASE_SECRET_KEY;
  const GITHUB_TOKEN = env.GITHUB_TOKEN;
  const GITHUB_REPOSITORY = env.GITHUB_REPOSITORY;
  const GITHUB_REF = env.GITHUB_REF ?? "main";

  if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY || !SUPABASE_SECRET_KEY ||
      !GITHUB_TOKEN || !GITHUB_REPOSITORY) {
    return json({ error: "server_not_configured" }, 500);
  }

  let body: { job_id?: string };
  try { body = await req.json(); }
  catch { return json({ error: "invalid_json" }, 400); }

  if (!isUuid(body.job_id)) return json({ error: "invalid_job_id" }, 400);
  const jobId = body.job_id;

  // User-context read: RLS proves caller owns the job.
  const visibleJob = await fetch(
    `${SUPABASE_URL}/rest/v1/jobs?id=eq.${encodeURIComponent(jobId)}&select=id,status&limit=1`,
    { headers: { apikey: SUPABASE_PUBLISHABLE_KEY, Authorization: auth } },
  );

  if (!visibleJob.ok) return json({ error: "job_lookup_failed" }, 502);
  const rows = await visibleJob.json();
  if (!Array.isArray(rows) || rows.length !== 1) return json({ error: "job_not_found" }, 404);
  if (rows[0].status !== "queued") return json({ error: "job_not_queueable" }, 409);

  // Guarded queued -> dispatched transition under server credentials.
  const claim = await fetch(
    `${SUPABASE_URL}/rest/v1/jobs?id=eq.${encodeURIComponent(jobId)}&status=eq.queued`,
    {
      method: "PATCH",
      headers: {
        apikey: SUPABASE_SECRET_KEY,
        Authorization: `Bearer ${SUPABASE_SECRET_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({
        status: "dispatched",
        stage: "dispatch",
        dispatched_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }),
    },
  );

  if (!claim.ok) return json({ error: "dispatch_claim_failed" }, 502);
  const claimed = await claim.json();
  if (!Array.isArray(claimed) || claimed.length !== 1) {
    return json({ error: "job_already_claimed" }, 409);
  }

  const dispatch = await fetch(
    `https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/process-memo.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: GITHUB_REF, inputs: { job_id: jobId } }),
    },
  );

  if (!dispatch.ok) return json({ error: "github_dispatch_failed" }, 502);
  return json({ ok: true, job_id: jobId, status: "dispatched" }, 202);
});
