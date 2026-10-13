const SUBJECT_LABELS = Object.freeze({
  mathematics: "Mathematics",
  fs_mathematics: "FS Mathematics",
});

export const DEPARTMENTS = Object.freeze(Object.entries(SUBJECT_LABELS).map(([value, label]) => ({ value, label })));
export const WORK_STATES = Object.freeze([
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
]);
export const PAPER_SCOPES = Object.freeze([
  { value: "all", label: "All papers" },
  { value: "my", label: "My papers" },
]);
export const FORMS = Object.freeze([1, 2, 3, 4, 5]);

export function subjectScope(value) {
  const normalized = String(value || "").replace(/\s+/g, " ").trim().toUpperCase();
  if (normalized === "MATHEMATICS") return "mathematics";
  if (normalized === "FS MATHEMATICS") return "fs_mathematics";
  return null;
}

export function formNumber(value) {
  const normalized = String(value || "").replace(/\s+/g, " ").trim().toUpperCase();
  const formMatch = normalized.match(/^FORM ([1-5])$/);
  if (formMatch) return Number(formMatch[1]);
  const gradeMatch = normalized.match(/^GRADE (8|9|10|11|12)$/);
  return gradeMatch ? Number(gradeMatch[1]) - 7 : null;
}

function workflowBucket(status) {
  return status === "complete" ? "completed" : "in_progress";
}

function ownerName(user) {
  return user?.app_metadata?.pbhs_display_name || user?.email || null;
}

export function ownerJobPaper(job, user) {
  const metadata = job?.teacher_metadata?.values || {};
  return {
    job_id: job.id,
    owner_user_id: job.user_id,
    owner_display_name: ownerName(user),
    subject_scope: subjectScope(metadata.subject),
    subject_display: metadata.subject || null,
    assessment_type: metadata.exam_type || null,
    term: metadata.term || null,
    year: metadata.year ?? null,
    paper: metadata.paper || null,
    grade_label: metadata.grade_label || null,
    form: formNumber(metadata.grade_label),
    workflow_bucket: workflowBucket(job.status),
    status_source: job.status,
    stage_source: job.stage,
    updated_at: job.updated_at || job.created_at,
    source_filename: job.source_filename || null,
    source: "owner_job",
    owner_job: job,
  };
}

export function libraryPaper(row, ownerJobs = new Map()) {
  const ownerJob = ownerJobs.get(row.job_id) || null;
  return {
    job_id: row.job_id,
    owner_user_id: row.owner_user_id,
    owner_display_name: row.owner_display_name || null,
    subject_scope: row.subject_scope || null,
    subject_display: row.subject_display || null,
    assessment_type: row.assessment_type || null,
    term: row.term || null,
    year: row.year ?? null,
    paper: row.paper || null,
    grade_label: row.grade_label || null,
    form: formNumber(row.grade_label),
    workflow_bucket: row.workflow_bucket,
    status_source: row.status_source,
    stage_source: row.stage_source,
    updated_at: row.updated_at || row.created_at,
    source_filename: row.source_filename || null,
    source: "department_summary",
    owner_job: ownerJob,
  };
}

export function filterPapers(papers, { department, workState, scope, form, ownerId }) {
  return papers.filter((paper) =>
    paper.subject_scope === department &&
    paper.workflow_bucket === workState &&
    paper.form === Number(form) &&
    (scope !== "my" || paper.owner_user_id === ownerId)
  );
}

export function papersForScope({ scope, ownerPapers, libraryRows, ownerId }) {
  if (scope === "my") return ownerPapers.filter((paper) => paper.owner_user_id === ownerId);
  const ownerJobs = new Map(ownerPapers.map((paper) => [paper.job_id, paper.owner_job]));
  return libraryRows.map((row) => libraryPaper(row, ownerJobs));
}

export function unclassifiedOwnerPapers(papers, { ownerId, workState }) {
  return papers.filter((paper) =>
    paper.owner_user_id === ownerId &&
    paper.workflow_bucket === workState &&
    (!paper.subject_scope || !paper.form)
  );
}

export function paperIdentity(paper) {
  const metadataTitle = [paper.assessment_type, paper.paper].filter(Boolean).join(" · ");
  return metadataTitle || paper.source_filename || "Memo details not recorded";
}

export function paperContext(paper) {
  return [paper.grade_label, paper.term, paper.year].filter((value) => value != null && value !== "");
}
