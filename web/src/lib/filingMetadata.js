export const SUBJECT_OPTIONS = Object.freeze([
  { value: "mathematics", label: "Mathematics" },
  { value: "fs_mathematics", label: "FS Mathematics" },
]);
export const FORM_OPTIONS = Object.freeze([1, 2, 3, 4, 5].map((value) => ({ value, label: `Form ${value}` })));
export const ASSESSMENT_TYPE_OPTIONS = Object.freeze([
  { value: "class_test", label: "Class Test" },
  { value: "standardised_test", label: "Standardised Test" },
  { value: "investigation", label: "Investigation" },
  { value: "examination", label: "Examination" },
]);
export const TERM_OPTIONS = Object.freeze([1, 2, 3, 4].map((value) => ({ value, label: `Term ${value}` })));
export const DURATION_UNIT_OPTIONS = Object.freeze([
  { value: "minutes", label: "Minutes" },
  { value: "hours", label: "Hours" },
  { value: "periods", label: "Periods" },
]);

const SUBJECTS = new Set(SUBJECT_OPTIONS.map(({ value }) => value));
const ASSESSMENT_TYPES = new Set(ASSESSMENT_TYPE_OPTIONS.map(({ value }) => value));
const DURATION_UNITS = new Set(DURATION_UNIT_OPTIONS.map(({ value }) => value));
const DISPLAY_NAME_MAX = 120;

export function allowedYears(now = new Date()) {
  const current = now.getFullYear();
  return Array.from({ length: 12 }, (_, index) => current + 1 - index);
}

export function initialFilingDraft(context = {}, now = new Date()) {
  context ||= {};
  return {
    subject_scope: SUBJECTS.has(context.department) ? context.department : "",
    form: Number.isInteger(Number(context.form)) && Number(context.form) >= 1 && Number(context.form) <= 5
      ? Number(context.form) : "",
    assessment_type: "",
    term: "",
    year: now.getFullYear(),
    assessment_number: "",
    paper: "",
    duration_value: "",
    duration_unit: "minutes",
  };
}

export function sanitizeDisplayName(value) {
  return String(value ?? "")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, " ")
    .replace(/\.{2,}/g, ".")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[. ]+$/g, "")
    .slice(0, DISPLAY_NAME_MAX)
    .trim();
}

function label(options, value) {
  return options.find((item) => item.value === value)?.label || "";
}

export function suggestedDisplayName(draft) {
  const assessment = label(ASSESSMENT_TYPE_OPTIONS, draft.assessment_type);
  const parts = [draft.form ? `Form ${draft.form}` : "", assessment];
  if (["class_test", "standardised_test"].includes(draft.assessment_type) && draft.assessment_number) {
    parts.push(String(draft.assessment_number));
  }
  if (draft.assessment_type === "examination" && draft.paper) parts.push(`Paper ${draft.paper}`);
  if (draft.term) parts.push(`Term ${draft.term}`);
  if (draft.year) parts.push(String(draft.year));
  return sanitizeDisplayName(parts.filter(Boolean).join(" "));
}

export function validateFilingDraft(draft, displayName, now = new Date()) {
  const errors = {};
  if (!SUBJECTS.has(draft.subject_scope)) errors.subject_scope = "Choose a subject.";
  if (!Number.isInteger(Number(draft.form)) || Number(draft.form) < 1 || Number(draft.form) > 5) errors.form = "Choose Form 1 to Form 5.";
  if (!ASSESSMENT_TYPES.has(draft.assessment_type)) errors.assessment_type = "Choose an assessment type.";
  if (!Number.isInteger(Number(draft.term)) || Number(draft.term) < 1 || Number(draft.term) > 4) errors.term = "Choose Term 1 to Term 4.";
  if (!allowedYears(now).includes(Number(draft.year))) errors.year = "Choose a year from the list.";

  const numbered = ["class_test", "standardised_test"].includes(draft.assessment_type);
  if (numbered && (![1, 2, 3, 4].includes(Number(draft.assessment_number)))) {
    errors.assessment_number = "Choose assessment number 1 to 4.";
  } else if (!numbered && draft.assessment_number !== "" && draft.assessment_number != null) {
    errors.assessment_number = "Assessment number does not apply to this assessment type.";
  }
  if (draft.assessment_type === "examination" && ![1, 2].includes(Number(draft.paper))) {
    errors.paper = "Choose Paper 1 or Paper 2.";
  } else if (draft.assessment_type && draft.assessment_type !== "examination" && draft.paper !== "" && draft.paper != null) {
    errors.paper = "Paper does not apply to this assessment type.";
  }

  const duration = Number(draft.duration_value);
  if (!DURATION_UNITS.has(draft.duration_unit)) errors.duration_unit = "Choose a time unit.";
  if (!Number.isFinite(duration) || duration <= 0) errors.duration_value = "Enter a positive time allocation.";
  else if (draft.duration_unit === "minutes" && (!Number.isInteger(duration) || duration > 720)) errors.duration_value = "Enter 1 to 720 whole minutes.";
  else if (draft.duration_unit === "hours" && duration > 12) errors.duration_value = "Enter no more than 12 hours.";
  else if (draft.duration_unit === "periods" && (!Number.isInteger(duration) || duration > 20)) errors.duration_value = "Enter 1 to 20 whole periods.";

  const cleanName = sanitizeDisplayName(displayName);
  if (!cleanName) errors.display_name = "Enter a document name.";
  else if (String(displayName).length > DISPLAY_NAME_MAX) errors.display_name = `Use no more than ${DISPLAY_NAME_MAX} characters.`;
  return { valid: Object.keys(errors).length === 0, errors, displayName: cleanName };
}

export function serializeFilingMetadata(draft) {
  const numbered = ["class_test", "standardised_test"].includes(draft.assessment_type);
  const examination = draft.assessment_type === "examination";
  const durationValue = Number(draft.duration_value);
  return {
    schema_version: "1.0",
    subject_scope: draft.subject_scope,
    form: Number(draft.form),
    assessment_type: draft.assessment_type,
    term: Number(draft.term),
    year: Number(draft.year),
    assessment_number: numbered
      ? { applicability: "required", value: Number(draft.assessment_number) }
      : { applicability: "not_applicable", value: null },
    paper: examination
      ? { applicability: "required", value: Number(draft.paper) }
      : { applicability: "not_applicable", value: null },
    duration: {
      value: durationValue,
      unit: draft.duration_unit,
      duration_minutes: draft.duration_unit === "minutes" ? durationValue
        : draft.duration_unit === "hours" ? Math.round(durationValue * 60) : null,
    },
  };
}

export function outputDownloadName(job, format) {
  const sourceStem = String(job?.source_filename || "Converted memo").replace(/\.[^.]+$/, "");
  const base = sanitizeDisplayName(job?.display_name || sourceStem) || "Converted memo";
  return `${base} - GDE Memo.${format}`;
}
