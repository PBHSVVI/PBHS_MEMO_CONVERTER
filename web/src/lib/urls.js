const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function reviewUrl(jobId, currentHref = window.location.href) {
  if (!UUID_RE.test(jobId || "")) throw new Error("Invalid review job ID.");
  const url = new URL("../phase7-5-review/", currentHref);
  url.searchParams.set("job_id", jobId);
  url.searchParams.set("v", "4.7");
  return url.toString();
}

export function outputPath(userId, jobId, format) {
  if (!UUID_RE.test(userId || "") || !UUID_RE.test(jobId || "")) {
    throw new Error("Invalid download identity.");
  }
  if (!["docx", "pdf"].includes(format)) throw new Error("Unsupported output format.");
  return `${userId}/${jobId}/output/memo.${format}`;
}
