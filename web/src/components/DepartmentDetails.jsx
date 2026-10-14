import { useEffect, useMemo, useState } from "react";
import {
  allowedYears,
  ASSESSMENT_TYPE_OPTIONS,
  DURATION_UNIT_OPTIONS,
  FORM_OPTIONS,
  initialFilingDraft,
  sanitizeDisplayName,
  SUBJECT_OPTIONS,
  suggestedDisplayName,
  TERM_OPTIONS,
  validateFilingDraft,
} from "../lib/filingMetadata";

export function DepartmentDetails({ initialContext, busy, onChange }) {
  const [draft, setDraft] = useState(() => initialFilingDraft(initialContext));
  const suggested = useMemo(() => suggestedDisplayName(draft), [draft]);
  const [displayName, setDisplayName] = useState(suggested);
  const [customName, setCustomName] = useState(false);
  const validation = useMemo(() => validateFilingDraft(draft, displayName), [draft, displayName]);

  useEffect(() => {
    if (!customName) setDisplayName(suggested);
  }, [customName, suggested]);

  useEffect(() => {
    onChange({ draft, displayName, validation });
  }, [displayName, draft, onChange, validation]);

  function update(field, value) {
    setDraft((current) => {
      const next = { ...current, [field]: value };
      if (field === "assessment_type") {
        if (!["class_test", "standardised_test"].includes(value)) next.assessment_number = "";
        if (value !== "examination") next.paper = "";
      }
      return next;
    });
  }

  const field = (name, label, control) => (
    <label className={validation.errors[name] ? "metadata-invalid" : ""}>
      {label}
      {control}
      {validation.errors[name] && <small className="field-error">{validation.errors[name]}</small>}
    </label>
  );
  const numbered = ["class_test", "standardised_test"].includes(draft.assessment_type);
  const examination = draft.assessment_type === "examination";

  return (
    <section className="department-details" aria-labelledby="department-details-title">
      <h2 id="department-details-title">Department details</h2>
      <p>These details are used to file the assessment correctly in the Mathematics Department library.</p>
      <div className="metadata-grid metadata-grid--document">
        {field("subject_scope", "Subject", <select value={draft.subject_scope} onChange={(e) => update("subject_scope", e.target.value)} disabled={busy}><option value="">Choose subject</option>{SUBJECT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>)}
        {field("form", "Form", <select value={draft.form} onChange={(e) => update("form", e.target.value)} disabled={busy}><option value="">Choose form</option>{FORM_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>)}
        {field("assessment_type", "Assessment type", <select value={draft.assessment_type} onChange={(e) => update("assessment_type", e.target.value)} disabled={busy}><option value="">Choose assessment type</option>{ASSESSMENT_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>)}
        {field("term", "Term", <select value={draft.term} onChange={(e) => update("term", e.target.value)} disabled={busy}><option value="">Choose term</option>{TERM_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>)}
        {field("year", "Year", <select value={draft.year} onChange={(e) => update("year", e.target.value)} disabled={busy}>{allowedYears().map((year) => <option key={year} value={year}>{year}</option>)}</select>)}
        {numbered ? field("assessment_number", "Assessment number", <select value={draft.assessment_number} onChange={(e) => update("assessment_number", e.target.value)} disabled={busy}><option value="">Choose number</option>{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}</select>) : <div className="not-applicable"><span>Assessment number</span><strong>Not applicable</strong></div>}
        {examination ? field("paper", "Paper", <select value={draft.paper} onChange={(e) => update("paper", e.target.value)} disabled={busy}><option value="">Choose paper</option><option value="1">Paper 1</option><option value="2">Paper 2</option></select>) : <div className="not-applicable"><span>Paper</span><strong>Not applicable</strong></div>}
        <fieldset className={validation.errors.duration_value || validation.errors.duration_unit ? "metadata-invalid" : ""}>
          <legend>Time allocation</legend>
          <div className="duration-fields">
            <input aria-label="Time allocation value" type="number" min="0" step={draft.duration_unit === "hours" ? "0.1" : "1"} value={draft.duration_value} onChange={(e) => update("duration_value", e.target.value)} disabled={busy} />
            <select aria-label="Time allocation unit" value={draft.duration_unit} onChange={(e) => update("duration_unit", e.target.value)} disabled={busy}>{DURATION_UNIT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
          </div>
          {(validation.errors.duration_value || validation.errors.duration_unit) && <small className="field-error">{validation.errors.duration_value || validation.errors.duration_unit}</small>}
        </fieldset>
      </div>
      <label className={`document-name-field${validation.errors.display_name ? " metadata-invalid" : ""}`}>
        Document name
        <input value={displayName} onChange={(e) => { setCustomName(true); setDisplayName(e.target.value); }} onBlur={() => setDisplayName((value) => sanitizeDisplayName(value))} disabled={busy} />
        <small>We've created this name from the department details. Change it only if you need to.</small>
        {validation.errors.display_name && <small className="field-error">{validation.errors.display_name}</small>}
      </label>
      {customName && <button type="button" className="button quiet reset-name" onClick={() => { setCustomName(false); setDisplayName(suggested); }} disabled={busy}>Reset to suggested name</button>}
    </section>
  );
}
