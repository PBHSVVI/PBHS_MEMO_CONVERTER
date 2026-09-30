import { useState } from "react";
import { createAndDispatchJob } from "../lib/memoService";
import { validateMemoFile } from "../lib/jobContracts";

const STEP_COPY = {
  creating: "Creating conversion…",
  uploading: "Uploading memo…",
  dispatching: "Starting conversion…",
  started: "Conversion started.",
};

export function UploadMemo({ client, user, onBack, onCreated }) {
  const [file, setFile] = useState(null);
  const [state, setState] = useState({ busy: false, message: "", error: "" });

  function choose(event) {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    const validation = validateMemoFile(selected);
    setState({
      busy: false,
      message: validation.ok ? `${selected.name} • ${(selected.size / 1024 / 1024).toFixed(1)} MB` : "",
      error: validation.ok ? "" : validation.message,
    });
  }

  async function submit(event) {
    event.preventDefault();
    const validation = validateMemoFile(file);
    if (!validation.ok) {
      setState({ busy: false, message: "", error: validation.message });
      return;
    }
    setState({ busy: true, message: "Preparing upload…", error: "" });
    try {
      const job = await createAndDispatchJob({
        client,
        user,
        file,
        onStep: (step) => setState({ busy: true, message: STEP_COPY[step], error: "" }),
      });
      onCreated(job);
    } catch (error) {
      setState({ busy: false, message: "", error: error.message });
    }
  }

  return (
    <main className="page-shell narrow">
      <button className="back-link" onClick={onBack}>← Recent conversions</button>
      <section className="panel upload-panel">
        <p className="eyebrow">New conversion</p>
        <h1>Upload your memo</h1>
        <p className="lede">Choose the source memo you want converted. The original stays unchanged.</p>
        <form onSubmit={submit}>
          <label className="drop-zone">
            <span className="upload-icon" aria-hidden="true">↑</span>
            <strong>{file ? "Choose a different file" : "Choose a memo file"}</strong>
            <span>PDF, Word DOCX, PNG, or JPEG • maximum 50 MB</span>
            <input
              type="file"
              accept=".pdf,.docx,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg"
              onChange={choose}
              disabled={state.busy}
            />
          </label>
          {state.message && <p className="notice info" aria-live="polite">{state.message}</p>}
          {state.error && <p className="notice danger" role="alert">{state.error}</p>}
          <div className="button-row">
            <button type="button" className="button secondary" onClick={onBack} disabled={state.busy}>Cancel</button>
            <button className="button primary" disabled={!file || state.busy}>
              {state.busy ? "Working…" : "Upload and convert"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
