import { useCallback, useRef, useState } from "react";
import { createAndDispatchJob } from "../lib/memoService";
import { validateMemoFile } from "../lib/jobContracts";
import { serializeFilingMetadata } from "../lib/filingMetadata";
import { DepartmentDetails } from "./DepartmentDetails";
import { SupportIncident } from "./SupportIncident";

const STEP_COPY = {
  creating: "Creating conversion…",
  uploading: "Uploading memo…",
  dispatching: "Starting conversion…",
  started: "Conversion started.",
};

export function UploadMemo({ client, user, onBack, onCreated, onJobCreated = () => {}, initialContext = null }) {
  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [filing, setFiling] = useState({ draft: null, displayName: "", validation: { valid: false, errors: {} } });
  const [currentJob, setCurrentJob] = useState(null);
  const [state, setState] = useState({ busy: false, message: "", error: "", errorCode: null });
  const dragDepth = useRef(0);
  const submissionLock = useRef(false);
  const currentJobRef = useRef(null);
  const updateFiling = useCallback((next) => setFiling(next), []);

  function acceptFile(selected) {
    const validation = validateMemoFile(selected);
    setFile(validation.ok ? selected : null);
    setState({
      busy: false,
      message: validation.ok ? `${selected.name} • ${(selected.size / 1024 / 1024).toFixed(1)} MB` : "",
      error: validation.ok ? "" : validation.message,
      errorCode: validation.ok ? null : "FILE_INVALID",
    });
  }

  function choose(event) {
    acceptFile(event.target.files?.[0] || null);
  }

  function dragEnter(event) {
    event.preventDefault();
    event.stopPropagation();
    if (state.busy) return;
    dragDepth.current += 1;
    setDragActive(true);
  }

  function dragOver(event) {
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer) event.dataTransfer.dropEffect = state.busy ? "none" : "copy";
  }

  function dragLeave(event) {
    event.preventDefault();
    event.stopPropagation();
    if (state.busy) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (!dragDepth.current) setDragActive(false);
  }

  function drop(event) {
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current = 0;
    setDragActive(false);
    if (state.busy) return;
    const dropped = Array.from(event.dataTransfer?.files || []);
    if (dropped.length !== 1) {
      setFile(null);
      setState({ busy: false, message: "", error: "Drop exactly one memo file at a time.", errorCode: "FILE_SELECTION_INVALID" });
      return;
    }
    acceptFile(dropped[0]);
  }

  async function submit(event) {
    event.preventDefault();
    if (submissionLock.current) return;
    const validation = validateMemoFile(file);
    if (!validation.ok) {
      setState({ busy: false, message: "", error: validation.message, errorCode: "FILE_INVALID" });
      return;
    }
    if (!filing.validation.valid || !filing.draft) {
      setState({ busy: false, message: "", error: "Please complete the highlighted department details before uploading.", errorCode: "DEPARTMENT_DETAILS_INVALID" });
      return;
    }
    submissionLock.current = true;
    setDragActive(false);
    setState({ busy: true, message: "Preparing upload…", error: "", errorCode: null });
    try {
      const job = await createAndDispatchJob({
        client,
        user,
        file,
        filingMetadata: serializeFilingMetadata(filing.draft),
        displayName: filing.validation.displayName,
        onStep: (step) => setState({ busy: true, message: STEP_COPY[step], error: "", errorCode: null }),
        onJobCreated: (job) => {
          currentJobRef.current = job;
          setCurrentJob(job);
          onJobCreated(job);
        },
      });
      onCreated(job);
    } catch (error) {
      submissionLock.current = false;
      const failedJob = error.details?.job || currentJobRef.current;
      if (error.code === "DISPATCH_FAILED" && failedJob) {
        onCreated(failedJob);
        return;
      }
      setState({ busy: false, message: "", error: error.message, errorCode: error.code || "UPLOAD_FAILED" });
    }
  }

  return (
    <main className="page-shell narrow">
      <button className="back-link" onClick={onBack}>← Recent conversions</button>
      <section className="panel upload-panel">
        <p className="eyebrow">New conversion</p>
        <h1>Upload your memo</h1>
        <p className="lede">Choose the source memo you want converted. The original stays unchanged.</p>
        <form onSubmit={submit} noValidate>
          <label
            className={`drop-zone${dragActive ? " drag-active" : ""}${state.busy ? " disabled" : ""}`}
            onDragEnter={dragEnter}
            onDragOver={dragOver}
            onDragLeave={dragLeave}
            onDrop={drop}
            aria-disabled={state.busy}
          >
            <span className="upload-icon" aria-hidden="true">↑</span>
            <strong>{dragActive ? "Drop one memo here" : file ? "Choose a different file" : "Choose or drop a memo file"}</strong>
            <span>PDF, Word DOCX, PNG, or JPEG • maximum 50 MB</span>
            <input
              type="file"
              accept=".pdf,.docx,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg"
              onChange={choose}
              disabled={state.busy}
            />
          </label>
          <DepartmentDetails initialContext={initialContext} busy={state.busy} onChange={updateFiling} />
          {state.message && <p className="notice info" aria-live="polite">{state.message}</p>}
          {state.error && <p className="notice danger" role="alert">{state.error}</p>}
          {state.error && (
            <SupportIncident
              client={client}
              user={user}
              label="Report this error"
              context={{
                job: currentJob ? { ...currentJob, error_code: state.errorCode || currentJob.error_code } : null,
                currentView: "upload_error",
              }}
            />
          )}
          <div className="button-row">
            <button type="button" className="button secondary" onClick={onBack} disabled={state.busy}>Cancel</button>
            <button className="button primary" disabled={!file || !filing.validation.valid || state.busy}>
              {state.busy ? "Working…" : "Upload and convert"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
