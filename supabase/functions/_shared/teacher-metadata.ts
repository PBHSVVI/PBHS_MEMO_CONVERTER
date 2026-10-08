export const SUPPORTED_METADATA_FIELDS = [
  "subject",
  "paper",
  "exam_type",
  "year",
  "grade_label",
  "duration_minutes",
] as const;

type MetadataField = typeof SUPPORTED_METADATA_FIELDS[number];
type MetadataValue = string | number;
export type TeacherMetadata = {
  schema_version: "1.0";
  values: Partial<Record<MetadataField, MetadataValue>>;
  confirmed_absent: MetadataField[];
};

const SUPPORTED = new Set<string>(SUPPORTED_METADATA_FIELDS);
const OUTER = new Set(["schema_version", "values", "confirmed_absent"]);
const encoder = new TextEncoder();

export class TeacherMetadataError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "TeacherMetadataError";
    this.code = code;
  }
}

function compactText(value: unknown, field: string, maximum: number): string {
  if (typeof value !== "string") {
    throw new TeacherMetadataError("invalid_field", `${field} must be text`);
  }
  const result = value.replace(/\s+/g, " ").trim();
  if (!result || result.length > maximum) {
    throw new TeacherMetadataError(
      "invalid_field",
      `${field} must contain 1 to ${maximum} characters`,
    );
  }
  return result;
}

function normalizeField(field: MetadataField, value: unknown): MetadataValue {
  if (field === "subject" || field === "exam_type") {
    return compactText(value, field, 80).toUpperCase();
  }
  if (field === "paper") {
    const match = compactText(value, field, 20).match(/^PAPER\s*([12])$/i);
    if (!match) {
      throw new TeacherMetadataError(
        "invalid_field",
        "paper must be PAPER 1 or PAPER 2",
      );
    }
    return `PAPER ${match[1]}`;
  }
  if (field === "grade_label") {
    const match = compactText(value, field, 20).match(
      /^(FORM|GRADE)\s*([0-9]{1,2})$/i,
    );
    const number = match ? Number(match[2]) : 0;
    if (!match || number < 1 || number > 13) {
      throw new TeacherMetadataError(
        "invalid_field",
        "grade_label must be FORM 1-13 or GRADE 1-13",
      );
    }
    return `${match[1].toUpperCase()} ${number}`;
  }
  if (field === "year") {
    if (!Number.isInteger(value) || Number(value) < 2000 || Number(value) > 2100) {
      throw new TeacherMetadataError(
        "invalid_field",
        "year must be an integer from 2000 to 2100",
      );
    }
    return Number(value);
  }
  if (field === "duration_minutes") {
    if (!Number.isInteger(value) || Number(value) < 1 || Number(value) > 720) {
      throw new TeacherMetadataError(
        "invalid_field",
        "duration_minutes must be an integer from 1 to 720",
      );
    }
    return Number(value);
  }
  throw new TeacherMetadataError(
    "unknown_field",
    `unsupported teacher metadata field: ${field}`,
  );
}

export function normalizeTeacherMetadata(payload: unknown): TeacherMetadata {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new TeacherMetadataError(
      "invalid_payload",
      "teacher_metadata must be an object",
    );
  }
  if (encoder.encode(JSON.stringify(payload)).length > 4096) {
    throw new TeacherMetadataError(
      "payload_too_large",
      "teacher_metadata is too large",
    );
  }

  const record = payload as Record<string, unknown>;
  const unknownOuter = Object.keys(record).filter((key) => !OUTER.has(key));
  if (unknownOuter.length) {
    throw new TeacherMetadataError(
      "unknown_field",
      `unknown keys: ${unknownOuter.join(", ")}`,
    );
  }
  if ((record.schema_version ?? "1.0") !== "1.0") {
    throw new TeacherMetadataError(
      "invalid_schema",
      "unsupported teacher_metadata schema_version",
    );
  }

  const rawValues = record.values ?? {};
  if (!rawValues || typeof rawValues !== "object" || Array.isArray(rawValues)) {
    throw new TeacherMetadataError("invalid_payload", "values must be an object");
  }
  const valueRecord = rawValues as Record<string, unknown>;
  const unknownValues = Object.keys(valueRecord).filter(
    (key) => !SUPPORTED.has(key),
  );
  if (unknownValues.length) {
    throw new TeacherMetadataError(
      "unknown_field",
      `unsupported fields: ${unknownValues.join(", ")}`,
    );
  }

  const values: Partial<Record<MetadataField, MetadataValue>> = {};
  for (const [field, value] of Object.entries(valueRecord)) {
    values[field as MetadataField] = normalizeField(
      field as MetadataField,
      value,
    );
  }

  const rawAbsent = record.confirmed_absent ?? [];
  if (
    !Array.isArray(rawAbsent) ||
    rawAbsent.some((field) => typeof field !== "string")
  ) {
    throw new TeacherMetadataError(
      "invalid_payload",
      "confirmed_absent must be a field-name list",
    );
  }
  const unknownAbsent = rawAbsent.filter(
    (field): field is string => typeof field === "string" && !SUPPORTED.has(field),
  );
  if (unknownAbsent.length) {
    throw new TeacherMetadataError(
      "unknown_field",
      `unsupported confirmed_absent fields: ${unknownAbsent.join(", ")}`,
    );
  }
  const confirmed_absent = SUPPORTED_METADATA_FIELDS.filter(
    (field) => rawAbsent.includes(field),
  );
  const overlap = Object.keys(values).filter(
    (field) => confirmed_absent.includes(field as MetadataField),
  );
  if (overlap.length) {
    throw new TeacherMetadataError(
      "invalid_payload",
      `value and confirmed absence overlap: ${overlap.join(", ")}`,
    );
  }

  return { schema_version: "1.0", values, confirmed_absent };
}

type DispatchJob = { status: string; stage: string };
type DispatchPolicy =
  | { allowed: true; mode: "initial" | "review_resume" | "retry" }
  | { allowed: false; error: "metadata_not_editable" | "job_not_queueable" };

export function metadataDispatchPolicy(
  job: DispatchJob,
  hasMetadata: boolean,
): DispatchPolicy {
  if (hasMetadata) {
    if (job.status === "queued") return { allowed: true, mode: "initial" };
    if (
      job.status === "needs_review" &&
      job.stage === "phase8_1b_metadata_review"
    ) {
      return { allowed: true, mode: "review_resume" };
    }
    return { allowed: false, error: "metadata_not_editable" };
  }
  if (job.status === "queued" || job.status === "failed_retryable") {
    return { allowed: true, mode: "retry" };
  }
  return { allowed: false, error: "job_not_queueable" };
}
