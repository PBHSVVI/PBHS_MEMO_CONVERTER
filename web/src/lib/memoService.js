import { outputPath } from "./urls";
import { safeFilename, validateMemoFile } from "./jobContracts";

const JOB_COLUMNS = [
  "id",
  "user_id",
  "status",
  "stage",
  "source_filename",
  "source_mime",
  "source_path",
  "source_size_bytes",
  "attempt_count",
  "review_required",
  "engine_version",
  "error_code",
  "teacher_metadata",
  "teacher_metadata_revision",
  "teacher_metadata_updated_at",
  "created_at",
  "updated_at",
].join(",");

export class PilotAppError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "PilotAppError";
    this.code = code;
    this.details = details;
  }
}

function fail(error, code, message, details) {
  if (error) throw new PilotAppError(code, message, { ...details, cause: error });
}

export async function listRecentJobs(client, limit = 20) {
  const { data, error } = await client
    .from("jobs")
    .select(JOB_COLUMNS)
    .order("created_at", { ascending: false })
    .limit(limit);
  fail(error, "JOBS_LOAD_FAILED", "Your recent conversions could not be loaded.");
  return data || [];
}

export async function getJob(client, jobId) {
  const { data, error } = await client
    .from("jobs")
    .select(JOB_COLUMNS)
    .eq("id", jobId)
    .single();
  fail(error, "JOB_LOAD_FAILED", "This conversion could not be loaded.");
  return data;
}

export async function createAndDispatchJob({ client, user, file, teacherMetadata, onStep = () => {} }) {
  const validation = validateMemoFile(file);
  if (!validation.ok) throw new PilotAppError("FILE_INVALID", validation.message);
  if (!user?.id) throw new PilotAppError("AUTH_REQUIRED", "Sign in before uploading a memo.");

  const jobId = crypto.randomUUID();
  const filename = safeFilename(file.name);
  const sourcePath = `${user.id}/${jobId}/source/${filename}`;

  onStep("creating");
  const { data: job, error: createError } = await client
    .from("jobs")
    .insert({
      id: jobId,
      user_id: user.id,
      status: "queued",
      stage: "upload",
      source_filename: file.name,
      source_mime: validation.mime,
      source_path: sourcePath,
      source_size_bytes: file.size,
    })
    .select(JOB_COLUMNS)
    .single();
  fail(createError, "JOB_CREATE_FAILED", "The conversion record could not be created.");

  onStep("uploading");
  const { error: uploadError } = await client.storage
    .from("memo-files")
    .upload(sourcePath, file, {
      upsert: false,
      contentType: validation.mime,
      cacheControl: "no-cache",
    });
  fail(
    uploadError,
    "SOURCE_UPLOAD_FAILED",
    "The memo upload did not finish. Keep this page open and try the upload again.",
    { jobId, sourcePath },
  );

  onStep("dispatching");
  const { data: dispatch, error: dispatchError } = await client.functions.invoke(
    "dispatch-memo",
    { body: { job_id: jobId, teacher_metadata: teacherMetadata || { schema_version: "1.0", values: {}, confirmed_absent: [] } } },
  );
  fail(
    dispatchError,
    "DISPATCH_FAILED",
    "The memo was uploaded but conversion did not start. Open it from Recent conversions and retry.",
    { jobId },
  );

  onStep("started");
  return { ...job, status: dispatch?.status || "dispatched", stage: "dispatch" };
}

export async function retryJob(client, jobId) {
  const { data, error } = await client.functions.invoke("dispatch-memo", {
    body: { job_id: jobId },
  });
  fail(error, "RETRY_FAILED", "The conversion could not be restarted. Please try again.");
  return data;
}


export async function submitTeacherMetadata(client, jobId, teacherMetadata) {
  const { data, error } = await client.functions.invoke("dispatch-memo", {
    body: { job_id: jobId, teacher_metadata: teacherMetadata },
  });
  fail(error, "METADATA_SUBMIT_FAILED", "The document details could not be applied. Please try again.");
  return data;
}

export async function fetchCanonicalMetadata(client, userId, jobId) {
  const path = `${userId}/${jobId}/internal/canonical.json`;
  const { data, error } = await client.storage.from("memo-files").download(path);
  fail(error, "METADATA_LOAD_FAILED", "Document details could not be loaded.");
  const canonical = JSON.parse(await data.text());
  return {
    effective: canonical.document_metadata || {},
    provenance: canonical.audit?.metadata_resolution?.fields || {},
  };
}

export async function fetchOutput(client, userId, jobId, format) {
  const path = outputPath(userId, jobId, format);
  const { data, error } = await client.storage.from("memo-files").download(path);
  fail(error, "DOWNLOAD_FAILED", `The ${format.toUpperCase()} file could not be downloaded.`);
  return { blob: data, filename: `memo.${format}` };
}

export function saveBlob({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
