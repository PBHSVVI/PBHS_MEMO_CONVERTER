export const MAX_SOURCE_BYTES = 50 * 1024 * 1024;

export const SOURCE_TYPES = Object.freeze({
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
});

export const ACTIVE_JOB_STATUSES = new Set([
  "queued",
  "dispatched",
  "processing",
  "correction_confirmed",
  "rendering",
]);

export function extensionOf(name = "") {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}
export function validateMemoFile(file) {
  if (!file) return { ok: false, message: "Choose a memo file first." };
  const extension = extensionOf(file.name);
  const mime = SOURCE_TYPES[extension];
  if (!mime) {
    return {
      ok: false,
      message: "Choose a PDF, Word DOCX, PNG, or JPEG memo.",
    };
  }
  if (!Number.isFinite(file.size) || file.size <= 0) {
    return { ok: false, message: "The selected file is empty." };
  }
  if (file.size > MAX_SOURCE_BYTES) {
    return { ok: false, message: "The selected file is larger than 50 MB." };
  }
  return { ok: true, mime, extension };
}

export function safeFilename(name) {
  const extension = extensionOf(name);
  const base = name.slice(0, Math.max(0, name.length - extension.length));
  const cleaned = base
    .normalize("NFKC")
    .replace(/[^a-zA-Z0-9._ -]+/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[.-]+|[.-]+$/g, "")
    .slice(0, 100);
  return `${cleaned || "memo"}${extension}`;
}

const STATUS_COPY = Object.freeze({
  created: ["Uploading", "Preparing your upload."],
  queued: ["Queued", "Your memo is waiting to start."],
  dispatched: ["Starting", "The converter is starting."],
  processing: ["Converting", "Your memo is being read and checked."],
  needs_review: ["Needs review", "A teacher decision is needed before conversion can finish."],
  correction_pending: ["Needs review", "A saved correction still needs your attention."],
  correction_confirmed: ["Converting", "Your confirmed correction is being checked."],
  rendering: ["Preparing files", "The final Word and PDF files are being created."],
  complete: ["Ready", "Your converted memo is ready to download."],
  failed_retryable: ["Needs retry", "Conversion paused and can be tried again safely."],
  failed: ["Failed", "Conversion could not be completed."],
});

export function teacherStatus(job) {
  if (job?.status === "queued" && job?.stage === "dispatch_retry") {
    return {
      label: "Needs retry",
      detail: "Your memo was uploaded safely, but conversion did not start.",
      tone: "danger",
    };
  }
  const [label, detail] = STATUS_COPY[job?.status] || ["Processing", "Checking the latest conversion state."];
  return {
    label,
    detail,
    tone:
      job?.status === "complete"
        ? "success"
        : job?.status === "needs_review" || job?.status === "correction_pending"
          ? "review"
          : job?.status === "failed" || job?.status === "failed_retryable"
            ? "danger"
            : "active",
  };
}

export function teacherStage(job) {
  if (!job) return "Checking status";
  if (job.status === "needs_review" || job.status === "correction_pending") return "Preparing review";
  if (job.status === "complete") return "Final memo ready";
  if (job.status === "failed_retryable") return "Paused safely";
  if (job.status === "failed") return "Conversion stopped";

  const stages = {
    upload: "Upload received",
    dispatch: "Starting conversion",
    dispatch_retry: "Waiting to retry",
    ingestion: "Reading memo",
    normalization: "Reading memo",
    structure: "Checking structure and mathematics",
    semantic_interpretation: "Checking structure and mathematics",
    canonicalization: "Preparing final memo",
    phase5_render_ready: "Preparing final memo",
    rendering: "Creating final memo",
    complete: "Final memo ready",
  };
  return stages[job.stage] || teacherStatus(job).detail;
}

export function canReview(job) {
  return ["needs_review", "correction_pending"].includes(job?.status);
}

export function canRetry(job) {
  return job?.status === "failed_retryable" ||
    (job?.status === "queued" && job?.stage === "dispatch_retry");
}

export function canDownload(job) {
  return job?.status === "complete";
}
