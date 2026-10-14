export type FilingMetadata = {
  schema_version: "1.0";
  subject_scope: "mathematics" | "fs_mathematics";
  form: number;
  assessment_type: "class_test" | "standardised_test" | "investigation" | "examination";
  term: number;
  year: number;
  assessment_number: { applicability: "required"; value: number } | { applicability: "not_applicable"; value: null };
  paper: { applicability: "required"; value: number } | { applicability: "not_applicable"; value: null };
  duration: { value: number; unit: "minutes" | "hours" | "periods"; duration_minutes: number | null };
};

export class FilingMetadataError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "FilingMetadataError";
    this.code = code;
  }
}

const OUTER = new Set(["schema_version", "subject_scope", "form", "assessment_type", "term", "year", "assessment_number", "paper", "duration"]);
const SUBJECTS = new Set(["mathematics", "fs_mathematics"]);
const TYPES = new Set(["class_test", "standardised_test", "investigation", "examination"]);
const encoder = new TextEncoder();

function record(value: unknown, field: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new FilingMetadataError("invalid_field", `${field} must be an object`);
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: string[], field: string) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.join("|") !== wanted.join("|")) throw new FilingMetadataError("invalid_field", `${field} has unsupported or missing fields`);
}

export function normalizeDisplayName(value: unknown): string {
  if (typeof value !== "string") throw new FilingMetadataError("invalid_display_name", "display_name must be text");
  const normalized = value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, " ").replace(/\.{2,}/g, ".").replace(/\s+/g, " ").trim().replace(/[. ]+$/g, "");
  if (!normalized || normalized.length > 120 || normalized !== value.trim()) throw new FilingMetadataError("invalid_display_name", "display_name is empty, unsafe, or too long");
  return normalized;
}

export function normalizeFilingMetadata(payload: unknown, now = new Date()): FilingMetadata {
  const value = record(payload, "filing_metadata");
  if (encoder.encode(JSON.stringify(payload)).length > 4096) throw new FilingMetadataError("payload_too_large", "filing_metadata is too large");
  exactKeys(value, [...OUTER], "filing_metadata");
  if (value.schema_version !== "1.0") throw new FilingMetadataError("invalid_schema", "unsupported filing_metadata schema_version");
  if (!SUBJECTS.has(String(value.subject_scope))) throw new FilingMetadataError("invalid_subject", "subject_scope is not supported");
  if (!Number.isInteger(value.form) || Number(value.form) < 1 || Number(value.form) > 5) throw new FilingMetadataError("invalid_form", "form must be 1 to 5");
  if (!TYPES.has(String(value.assessment_type))) throw new FilingMetadataError("invalid_assessment_type", "assessment_type is not supported");
  if (!Number.isInteger(value.term) || Number(value.term) < 1 || Number(value.term) > 4) throw new FilingMetadataError("invalid_term", "term must be 1 to 4");
  const current = now.getUTCFullYear();
  if (!Number.isInteger(value.year) || Number(value.year) < current - 10 || Number(value.year) > current + 1) throw new FilingMetadataError("invalid_year", "year is outside the allowed filing range");

  const assessmentNumber = record(value.assessment_number, "assessment_number");
  const paper = record(value.paper, "paper");
  exactKeys(assessmentNumber, ["applicability", "value"], "assessment_number");
  exactKeys(paper, ["applicability", "value"], "paper");
  const numbered = value.assessment_type === "class_test" || value.assessment_type === "standardised_test";
  if (numbered) {
    if (assessmentNumber.applicability !== "required" || ![1, 2, 3, 4].includes(Number(assessmentNumber.value))) throw new FilingMetadataError("assessment_number_required", "assessment number 1 to 4 is required");
  } else if (assessmentNumber.applicability !== "not_applicable" || assessmentNumber.value !== null) {
    throw new FilingMetadataError("assessment_number_not_applicable", "assessment number does not apply");
  }
  if (value.assessment_type === "examination") {
    if (paper.applicability !== "required" || ![1, 2].includes(Number(paper.value))) throw new FilingMetadataError("paper_required", "paper 1 or 2 is required");
  } else if (paper.applicability !== "not_applicable" || paper.value !== null) {
    throw new FilingMetadataError("paper_not_applicable", "paper does not apply");
  }

  const duration = record(value.duration, "duration");
  exactKeys(duration, ["value", "unit", "duration_minutes"], "duration");
  const amount = Number(duration.value);
  const unit = String(duration.unit);
  if (!Number.isFinite(amount) || amount <= 0) throw new FilingMetadataError("invalid_duration", "duration must be positive");
  if (unit === "minutes") {
    if (!Number.isInteger(amount) || amount > 720 || duration.duration_minutes !== amount) throw new FilingMetadataError("invalid_duration", "minutes must be whole, bounded, and normalized exactly");
  } else if (unit === "hours") {
    if (amount > 12 || !Number.isInteger(amount * 60) || duration.duration_minutes !== Math.round(amount * 60)) throw new FilingMetadataError("invalid_duration", "hours must be bounded and normalized exactly");
  } else if (unit === "periods") {
    if (!Number.isInteger(amount) || amount > 20 || duration.duration_minutes !== null) throw new FilingMetadataError("invalid_duration", "periods must be whole, bounded, and have no minute conversion");
  } else throw new FilingMetadataError("invalid_duration", "duration unit is not supported");

  return value as FilingMetadata;
}
