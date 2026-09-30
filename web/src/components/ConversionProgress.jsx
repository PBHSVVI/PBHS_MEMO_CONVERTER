import { useCallback, useEffect, useState } from "react";
import {
  ACTIVE_JOB_STATUSES,
  canDownload,
  canRetry,
  canReview,
  teacherStage,
  teacherStatus,
} from "../lib/jobContracts";
import { fetchOutput, getJob, retryJob, saveBlob } from "../lib/memoService";
import { reviewUrl } from "../lib/urls";

const POLL_MS = 6000;

export function ConversionProgress({ client, user, initialJob, onBack }) {
  const [job, setJob] = useState(initialJob);
  const [state, setState] = useState({ busy: "", error: "" });
  const status = teacherStatus(job);

  const refresh = useCallback(async () => {
    try {
      setJob(await getJob(client, initialJob.id));
    } catch (error) {
      setState((current) => ({ ...current, error: error.message }));
    }
  }, [client, initialJob.id]);

  useEffect(() => {
    refresh();
    if (!ACTIVE_JOB_STATUSES.has(job?.status)) return undefined;
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [job?.status, refresh]);

  async function retry() {
    setState({ busy: "retry", error: "" });
    try {
      await retryJob(client, job.id);
      await refresh();
    } catch (error) {
      setState({ busy: "", error: error.message });
      return;
    }
    setState({ busy: "", error: "" });
  }

  async function download(format) {
    setState({ busy: format, error: "" });
    try {
      saveBlob(await fetchOutput(client, user.id, job.id, format));
    } catch (error) {
      setState({ busy: "", error: error.message });
      return;
    }
    setState({ busy: "", error: "" });
  }

  return (
    <main className="page-shell narrow">
      <button className="back-link" onClick={onBack}>← Recent conversions</button>
      <section className="panel progress-panel">
        <span className={`status-pill large ${status.tone}`}>{status.label}</span>
        <h1>{job.source_filename || "Memo conversion"}</h1>
        <p className="lede">{status.detail}</p>

        <div className="progress-track" aria-label="Conversion progress">
          <span className={`progress-dot ${job.status === "complete" ? "done" : ""}`} />
          <div>
            <strong>{teacherStage(job)}</strong>
            <p>Last updated {new Intl.DateTimeFormat("en-ZA", { dateStyle: "medium", timeStyle: "short" }).format(new Date(job.updated_at || job.created_at))}</p>
          </div>
        </div>

        {state.error && <p className="notice danger" role="alert">{state.error}</p>}

        {canReview(job) && (
          <div className="action-card review-card">
            <h2>Your judgement is needed</h2>
            <p>The converter found one or more items that a teacher should confirm.</p>
            <a className="button review" href={reviewUrl(job.id)}>Review memo</a>
          </div>
        )}

        {canDownload(job) && (
          <div className="action-card success-card">
            <h2>Your memo is ready</h2>
            <p>Download either format. Both files are private to your signed-in account.</p>
            <div className="button-row">
              <button className="button primary" onClick={() => download("docx")} disabled={Boolean(state.busy)}>
                {state.busy === "docx" ? "Downloading…" : "Download Word"}
              </button>
              <button className="button secondary" onClick={() => download("pdf")} disabled={Boolean(state.busy)}>
                {state.busy === "pdf" ? "Downloading…" : "Download PDF"}
              </button>
            </div>
          </div>
        )}

        {canRetry(job) && (
          <div className="action-card danger-card">
            <h2>Conversion paused safely</h2>
            <p>Your original memo and any confirmed review decisions are still saved. You can retry this conversion.</p>
            <button className="button primary" onClick={retry} disabled={state.busy === "retry"}>
              {state.busy === "retry" ? "Retrying…" : "Retry conversion"}
            </button>
            {job.error_code && (
              <details className="technical">
                <summary>Technical details</summary>
                <code>{job.error_code}</code>
              </details>
            )}
          </div>
        )}

        {job.status === "failed" && (
          <div className="action-card danger-card">
            <h2>This conversion could not finish</h2>
            <p>Please keep the original memo and contact the pilot support person before trying again.</p>
            {job.error_code && (
              <details className="technical">
                <summary>Technical details</summary>
                <code>{job.error_code}</code>
              </details>
            )}
          </div>
        )}

        {ACTIVE_JOB_STATUSES.has(job.status) && (
          <p className="poll-note">This page checks for progress every few seconds. You may return to Recent conversions and come back later.</p>
        )}
      </section>
    </main>
  );
}
