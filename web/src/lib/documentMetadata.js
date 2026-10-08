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

export function normalizeMetadataDraft(draft = {}) {
  const values = {};
  const textFields = ["subject", "exam_type", "grade_label"];
  for (const field of textFields) {
    const value = String(draft[field] || "").replace(/\s+/g, " ").trim();
    if (value) values[field] = value;
  }
  if (draft.paper) values.paper = draft.paper;
  if (draft.year !== "" && draft.year != null) values.year = Number(draft.year);
  if (draft.duration_value !== "" && draft.duration_value != null) {
    const amount = Number(draft.duration_value);
    values.duration_minutes = draft.duration_unit === "hours"
      ? Math.round(amount * 60)
      : Math.round(amount);
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
