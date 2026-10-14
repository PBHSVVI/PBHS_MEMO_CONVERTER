import { useEffect, useMemo, useState } from "react";
import {
  draftFromTeacherMetadata,
  FORM_OPTIONS,
  normalizeMetadataDraft,
} from "../lib/documentMetadata";

const LABELS = {
  subject: "Subject",
  paper: "Paper",
  exam_type: "Assessment Type",
  year: "Year",
  grade_label: "Form / Grade",
  duration_minutes: "Time allocation",
};

const ASSESSMENT_TYPES = [
  ["STANDARDISED TEST", "Standardised Test"],
  ["CLASS TEST", "Class Test"],
  ["INVESTIGATION", "Investigation"],
  ["EXAMINATION", "Examination"],
];

function AssessmentTypeField({ value, onChange, disabled, error = "" }) {
  return (
    <label className={error ? "metadata-invalid" : ""}>
      Assessment Type
      <select id="metadata-exam_type" value={value} onChange={onChange} aria-invalid={Boolean(error)} aria-describedby={error ? "metadata-exam_type-error" : undefined} disabled={disabled}>
        <option value="">Not supplied</option>
        {value && !ASSESSMENT_TYPES.some(([code]) => code === value) && (
          <option value={value}>{value}</option>
        )}
        {ASSESSMENT_TYPES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
      </select>
      {error && <small className="field-error" id="metadata-exam_type-error">{error}</small>}
    </label>
  );
}

export function DocumentDetails({
  mode = "upload",
  teacherMetadata,
  effectiveMetadata = {},
  provenance = {},
  missingFields = [],
  onChange = () => {},
  onSubmit,
  busy = false,
  errors = {},
  focusField = null,
}) {
  const [draft, setDraft] = useState(() => draftFromTeacherMetadata(teacherMetadata));
  const [error, setError] = useState("");
  const readonly = mode === "readonly";
  const review = mode === "review";
  const missing = useMemo(() => new Set(missingFields), [missingFields]);

  useEffect(() => {
    if (focusField) document.getElementById(`metadata-${focusField}`)?.focus();
  }, [focusField]);

  function fieldClass(field, base = "") {
    return [base, missing.has(field) ? "metadata-required" : "", errors[field] ? "metadata-invalid" : ""].filter(Boolean).join(" ");
  }

  function fieldError(field) {
    return errors[field] ? <small className="field-error" id={`metadata-${field}-error`}>{errors[field]}</small> : null;
  }

  function update(field, value) {
    const next = { ...draft, [field]: value };
    if (field !== "confirmed_absent") {
      next.confirmed_absent = next.confirmed_absent.filter((item) => item !== field);
    }
    setDraft(next);
    onChange(normalizeMetadataDraft(next));
  }

  async function submit(leaveBlank = false) {
    let next = draft;
    if (leaveBlank) {
      const confirmed = new Set(next.confirmed_absent);
      for (const field of missingFields) {
        const draftKey = field === "duration_minutes" ? "duration_value" : field;
        if (!String(next[draftKey] ?? "").trim()) confirmed.add(field);
      }
      next = { ...next, confirmed_absent: [...confirmed] };
      setDraft(next);
    } else {
      const unresolved = missingFields.filter((field) => {
        const draftKey = field === "duration_minutes" ? "duration_value" : field;
        return !String(next[draftKey] ?? "").trim() &&
          !next.confirmed_absent.includes(field);
      });
      if (unresolved.length) {
        setError("Enter the missing details, or choose Leave blank.");
        return;
      }
    }
    setError("");
    await onSubmit?.(normalizeMetadataDraft(next));
  }

  const sourceRows = Object.entries(effectiveMetadata).filter(
    ([field, value]) => value != null && provenance[field]?.selected_provenance === "source"
  );

  if (readonly) {
    return (
      <div className="metadata-readonly">
        {Object.entries(effectiveMetadata).filter(([, value]) => value != null).map(([field, value]) => (
          <div key={field}><span>{LABELS[field] || field}</span><strong>{String(value)}</strong><small>{provenance[field]?.selected_provenance === "source" ? "From source" : provenance[field]?.selected_provenance === "teacher" ? "Teacher supplied" : "Recorded detail"}</small></div>
        ))}
        {!Object.values(effectiveMetadata).some((value) => value != null) && <p>No document details were supplied.</p>}
        <p className="muted">Create a revised conversion to change document details.</p>
      </div>
    );
  }

  return (
    <div className="document-details">
      {sourceRows.length > 0 && review && (
        <div className="source-details">
          {sourceRows.map(([field, value]) => (
            <div key={field}><span>{LABELS[field] || field}</span><strong>{String(value)}</strong><small>From source</small></div>
          ))}
        </div>
      )}

      {(mode === "upload" || missing.has("grade_label")) && (
        <label className={fieldClass("grade_label")}>
          Form / Grade
          <select
            id="metadata-grade_label"
            value={draft.grade_label}
            onChange={(event) => update("grade_label", event.target.value)}
            aria-invalid={Boolean(errors.grade_label)}
            aria-describedby={errors.grade_label ? "metadata-grade_label-error" : undefined}
            disabled={busy}
          >
            <option value="">Not supplied</option>
            {review && draft.grade_label && !FORM_OPTIONS.some(({ value }) => value === draft.grade_label) && <option value={draft.grade_label}>{draft.grade_label}</option>}
            {FORM_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
          </select>
          {fieldError("grade_label")}
        </label>
      )}

      {(mode === "upload" || missing.has("duration_minutes")) && (
        <fieldset className={fieldClass("duration_minutes")}>
          <legend>Time allocation</legend>
          <div className="duration-fields">
            <input
              type="number"
              id="metadata-duration_minutes"
              min="0.5"
              max={draft.duration_unit === "hours" ? "12" : "720"}
              step={draft.duration_unit === "hours" ? "0.5" : "1"}
              value={draft.duration_value}
              onChange={(event) => update("duration_value", event.target.value)}
              aria-label="Time allocation value"
              aria-invalid={Boolean(errors.duration_minutes)}
              aria-describedby={errors.duration_minutes ? "metadata-duration_minutes-error" : undefined}
              disabled={busy}
            />
            <select
              value={draft.duration_unit}
              onChange={(event) => update("duration_unit", event.target.value)}
              aria-label="Time allocation unit"
              disabled={busy}
            >
              <option value="hours">hours</option>
              <option value="minutes">minutes</option>
            </select>
          </div>
          {fieldError("duration_minutes")}
        </fieldset>
      )}

      {mode === "upload" && (
        <div className="metadata-grid metadata-grid--document" data-future-field="term">
          <label className={fieldClass("subject")}>Subject<input id="metadata-subject" value={draft.subject} onChange={(event) => update("subject", event.target.value)} placeholder="Mathematics" aria-invalid={Boolean(errors.subject)} aria-describedby={errors.subject ? "metadata-subject-error" : undefined} disabled={busy} />{fieldError("subject")}</label>
          <AssessmentTypeField value={draft.exam_type} onChange={(event) => update("exam_type", event.target.value)} disabled={busy} error={errors.exam_type} />
          <label className={fieldClass("paper")}>Paper<select id="metadata-paper" value={draft.paper} onChange={(event) => update("paper", event.target.value)} aria-invalid={Boolean(errors.paper)} aria-describedby={errors.paper ? "metadata-paper-error" : undefined} disabled={busy}><option value="">Not supplied</option><option value="PAPER 1">Paper 1</option><option value="PAPER 2">Paper 2</option></select>{fieldError("paper")}</label>
          <label className={fieldClass("year")}>Year<input id="metadata-year" type="number" min="2000" max="2100" step="1" value={draft.year} onChange={(event) => update("year", event.target.value)} aria-invalid={Boolean(errors.year)} aria-describedby={errors.year ? "metadata-year-error" : undefined} disabled={busy} />{fieldError("year")}</label>
        </div>
      )}

      {review && ["paper", "year", "exam_type", "subject"].some(
        (field) => !provenance[field]?.source_present
      ) && (
        <details className="metadata-optional">
          <summary>Other document details (optional)</summary>
          <div className="metadata-grid metadata-grid--document" data-future-field="term">
            {!provenance.subject?.source_present && <label>Subject<input value={draft.subject} onChange={(event) => update("subject", event.target.value)} placeholder="Mathematics" disabled={busy} /></label>}
            {!provenance.exam_type?.source_present && <AssessmentTypeField value={draft.exam_type} onChange={(event) => update("exam_type", event.target.value)} disabled={busy} />}
            {!provenance.paper?.source_present && <label>Paper<select value={draft.paper} onChange={(event) => update("paper", event.target.value)} disabled={busy}><option value="">Not supplied</option><option value="PAPER 1">Paper 1</option><option value="PAPER 2">Paper 2</option></select></label>}
            {!provenance.year?.source_present && <label>Year<input type="number" min="2000" max="2100" value={draft.year} onChange={(event) => update("year", event.target.value)} disabled={busy} /></label>}
          </div>
        </details>
      )}

      {error && <p className="notice danger" role="alert">{error}</p>}
      {review && (
        <div className="button-row">
          <button type="button" className="button primary" onClick={() => submit(false)} disabled={busy}>{busy ? "Applying…" : "Apply details"}</button>
          <button type="button" className="button secondary" onClick={() => submit(true)} disabled={busy}>Leave blank</button>
        </div>
      )}
    </div>
  );
}
