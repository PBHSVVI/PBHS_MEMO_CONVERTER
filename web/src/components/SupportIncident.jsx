import { useState } from "react";
import { INCIDENT_TYPES, submitSupportIncident } from "../lib/supportIncidents";

export function SupportIncident({ client, user, context }) {
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("stuck");
  const [note, setNote] = useState("");
  const [state, setState] = useState({ busy: false, result: null, error: "", fallback: null });

  function close() {
    setOpen(false);
    setType("stuck");
    setNote("");
    setState({ busy: false, result: null, error: "", fallback: null });
  }

  async function submit(event) {
    event.preventDefault();
    setState({ busy: true, result: null, error: "", fallback: null });
    try {
      const result = await submitSupportIncident({ client, user, incidentType: type, teacherNote: note, context });
      setState({ busy: false, result, error: "", fallback: null });
    } catch (error) {
      setState({ busy: false, result: null, error: "We couldn't send the report.", fallback: error.fallbackReference || null });
    }
  }

  return (
    <>
      <button className="button support-action" onClick={() => setOpen(true)}>Help / Report a problem</button>
      {open && <div className="support-backdrop" role="presentation">
        <section className="support-dialog" role="dialog" aria-modal="true" aria-labelledby="support-title">
          <button className="support-close" aria-label="Close support form" onClick={close}>×</button>
          <p className="eyebrow">Teacher support</p>
          <h2 id="support-title">What happened?</h2>
          {state.result ? (
            <div className="support-result" role="status">
              <p><strong>Your report has been saved.</strong></p>
              <p>Reference: <strong>{state.result.reference}</strong></p>
              {state.result.notification_delayed && <p>Automatic notification is delayed. Please contact the Mathematics Department administrator and include this reference.</p>}
              <p>You can continue working if possible, or close this page and return later.</p>
              <button className="button primary" onClick={close}>Close</button>
            </div>
          ) : (
            <form onSubmit={submit}>
              <fieldset className="support-options">
                <legend className="sr-only">What happened?</legend>
                {INCIDENT_TYPES.map((option) => <label key={option.value}><input type="radio" name="incident-type" value={option.value} checked={type === option.value} onChange={() => setType(option.value)} /> {option.label}</label>)}
              </fieldset>
              <label>Anything else we should know?<textarea value={note} maxLength="1200" onChange={(event) => setNote(event.target.value)} /></label>
              <p className="support-reassurance">We'll save the current screen and job status so the Mathematics Department administrator can investigate. Your memo will not be reset.</p>
              {state.error && <div className="notice danger" role="alert"><strong>{state.error}</strong>{state.fallback && <p>Please contact the Mathematics Department administrator and include this reference: <strong>{state.fallback}</strong></p>}</div>}
              <div className="button-row"><button className="button primary" disabled={state.busy}>{state.busy ? "Sending…" : "Send report"}</button><button type="button" className="button quiet" onClick={close}>Cancel</button></div>
            </form>
          )}
        </section>
      </div>}
    </>
  );
}
