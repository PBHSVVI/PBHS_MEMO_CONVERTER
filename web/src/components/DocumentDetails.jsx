import { useMemo, useState } from "react";
import {
  draftFromTeacherMetadata,
  normalizeMetadataDraft,
} from "../lib/documentMetadata";

const LABELS = {
  subject: "Subject",
  paper: "Paper",
  exam_type: "Assessment type",
  year: "Year",
  grade_label: "Form / Grade",
  duration_minutes: "Time allocation",
};

export function DocumentDetails({
  mode = "upload",
  teacherMetadata,
  effectiveMetadata = {},
  provenance = {},
  missingFields = [],
  onChange = () => {},
  onSubmit,
  busy = false,
}) {
  const [draft, setDraft] = useState(() => draftFromTeacherMetadata(teacherMetadata));
  const [error, setError] = useState("");
  const readonly = mode === "readonly";
  const review = mode === "review";
  const missing = useMemo(() => new Set(missingFields), [missingFields]);

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
        <label className={missing.has("grade_label") ? "metadata-required" : ""}>
          Form / Grade
          <input
            value={draft.grade_label}
            onChange={(event) => update("grade_label", event.target.value)}
            placeholder="Form 5"
            disabled={busy}
          />
        </label>
      )}

      {(mode === "upload" || missing.has("duration_minutes")) && (
        <fieldset className={missing.has("duration_minutes") ? "metadata-required" : ""}>
          <legend>Time allocation</legend>
          <div className="duration-fields">
            <input
              type="number"
              min="0.5"
              max={draft.duration_unit === "hours" ? "12" : "720"}
              step={draft.duration_unit === "hours" ? "0.5" : "1"}
              value={draft.duration_value}
              onChange={(event) => update("duration_value", event.target.value)}
              aria-label="Time allocation value"
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
        </fieldset>
      )}

      {mode === "upload" && (
        <div className="metadata-grid">
          <label>Paper<select value={draft.paper} onChange={(event) => update("paper", event.target.value)} disabled={busy}><option value="">Not supplied</option><option value="PAPER 1">Paper 1</option><option value="PAPER 2">Paper 2</option></select></label>
          <label>Year<input type="number" min="2000" max="2100" value={draft.year} onChange={(event) => update("year", event.target.value)} disabled={busy} /></label>
          <label>Assessment type<input value={draft.exam_type} onChange={(event) => update("exam_type", event.target.value)} placeholder="Preparatory Examination" disabled={busy} /></label>
          <label>Subject<input value={draft.subject} onChange={(event) => update("subject", event.target.value)} placeholder="Mathematics" disabled={busy} /></label>
        </div>
      )}

      {review && ["paper", "year", "exam_type", "subject"].some(
        (field) => !provenance[field]?.source_present
      ) && (
        <details className="metadata-optional">
          <summary>Other document details (optional)</summary>
          <div className="metadata-grid">
            {!provenance.paper?.source_present && <label>Paper<select value={draft.paper} onChange={(event) => update("paper", event.target.value)} disabled={busy}><option value="">Not supplied</option><option value="PAPER 1">Paper 1</option><option value="PAPER 2">Paper 2</option></select></label>}
            {!provenance.year?.source_present && <label>Year<input type="number" min="2000" max="2100" value={draft.year} onChange={(event) => update("year", event.target.value)} disabled={busy} /></label>}
            {!provenance.exam_type?.source_present && <label>Assessment type<input value={draft.exam_type} onChange={(event) => update("exam_type", event.target.value)} placeholder="Preparatory Examination" disabled={busy} /></label>}
            {!provenance.subject?.source_present && <label>Subject<input value={draft.subject} onChange={(event) => update("subject", event.target.value)} placeholder="Mathematics" disabled={busy} /></label>}
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
