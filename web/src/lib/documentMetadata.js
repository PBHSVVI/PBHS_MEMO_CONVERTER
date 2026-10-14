export const METADATA_FIELDS = [
  "subject",
  "paper",
  "exam_type",
  "year",
  "grade_label",
  "duration_minutes",
];

export const EMPTY_TEACHER_METADATA = Object.freeze({
  schema_version: "1.0",
  values: Object.freeze({}),
  confirmed_absent: Object.freeze([]),
});

export const FORM_OPTIONS = Object.freeze([1, 2, 3, 4, 5].map((number) => ({
  value: `FORM ${number}`,
  label: `Form ${number}`,
})));

const ALLOWED_FIELDS = new Set(METADATA_FIELDS);
const FORM_VALUES = new Set(FORM_OPTIONS.map(({ value }) => value));
const PAPER_VALUES = new Set(["PAPER 1", "PAPER 2"]);
const ASSESSMENT_VALUES = new Set([
  "STANDARDISED TEST",
  "CLASS TEST",
  "INVESTIGATION",
  "EXAMINATION",
]);

function compactText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function uploadMetadataFromDashboard(context = {}) {
  const subject = context.department === "fs_mathematics"
    ? "FS MATHEMATICS"
    : context.department === "mathematics" ? "MATHEMATICS" : "";
  const form = Number(context.form);
  return normalizeMetadataDraft({
    subject,
    grade_label: Number.isInteger(form) && form >= 1 && form <= 5 ? `FORM ${form}` : "",
  });
}

export function validateTeacherMetadata(metadata = EMPTY_TEACHER_METADATA) {
  const errors = {};
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return { valid: false, errors: { metadata: "Document details are not valid." } };
  }
  const values = metadata.values;
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    return { valid: false, errors: { metadata: "Document details are not valid." } };
  }
  for (const field of Object.keys(values)) {
    if (!ALLOWED_FIELDS.has(field)) errors[field] = "This document detail is not supported.";
  }
  if ("subject" in values) {
    const value = compactText(values.subject);
    if (!value || value.length > 80) errors.subject = "Enter a subject using no more than 80 characters.";
  }
  if ("exam_type" in values && !ASSESSMENT_VALUES.has(values.exam_type)) {
    errors.exam_type = "Choose a listed assessment type.";
  }
  if ("paper" in values && !PAPER_VALUES.has(values.paper)) {
    errors.paper = "Choose Paper 1 or Paper 2.";
  }
  if ("grade_label" in values && !FORM_VALUES.has(values.grade_label)) {
    errors.grade_label = "Choose Form 1 to Form 5.";
  }
  if ("year" in values && (!Number.isInteger(values.year) || values.year < 2000 || values.year > 2100)) {
    errors.year = "Enter a whole year from 2000 to 2100.";
  }
  if ("duration_minutes" in values && (!Number.isInteger(values.duration_minutes) || values.duration_minutes < 1 || values.duration_minutes > 720)) {
    errors.duration_minutes = "Enter a time from 1 to 720 minutes.";
  }
  const confirmedAbsent = metadata.confirmed_absent;
  if (!Array.isArray(confirmedAbsent) || confirmedAbsent.some((field) => !ALLOWED_FIELDS.has(field))) {
    errors.metadata = "Document details are not valid.";
  } else if (confirmedAbsent.some((field) => field in values)) {
    errors.metadata = "A supplied detail cannot also be marked as absent.";
  }
  return { valid: Object.keys(errors).length === 0, errors };
}

export function normalizeMetadataDraft(draft = {}) {
  const values = {};
  const textFields = ["subject", "exam_type", "grade_label"];
  for (const field of textFields) {
    const value = compactText(draft[field]);
    if (value) values[field] = value.toUpperCase();
  }
  if (draft.paper) values.paper = draft.paper;
  if (draft.year !== "" && draft.year != null) values.year = Number(draft.year);
  if (draft.duration_value !== "" && draft.duration_value != null) {
    const amount = Number(draft.duration_value);
    values.duration_minutes = draft.duration_unit === "hours"
      ? amount * 60
      : amount;
  }
  const confirmed_absent = METADATA_FIELDS.filter((field) =>
    (draft.confirmed_absent || []).includes(field) && !(field in values)
  );
  return { schema_version: "1.0", values, confirmed_absent };
}

export function draftFromTeacherMetadata(metadata) {
  const values = metadata?.values || {};
  const duration = values.duration_minutes;
  return {
    subject: values.subject || "",
    paper: values.paper || "",
    exam_type: values.exam_type || "",
    year: values.year ?? "",
    grade_label: values.grade_label || "",
    duration_value: duration == null ? "" : duration % 60 === 0 ? duration / 60 : duration,
    duration_unit: duration == null || duration % 60 === 0 ? "hours" : "minutes",
    confirmed_absent: [...(metadata?.confirmed_absent || [])],
  };
}
