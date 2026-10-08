import { useCallback, useEffect, useState } from "react";
import {
  ACTIVE_JOB_STATUSES,
  canDownload,
  canRetry,
  canReview,
  teacherStage,
  teacherStatus,
} from "../lib/jobContracts";
import {
  fetchCanonicalMetadata,
  fetchOutput,
  getJob,
  retryJob,
  saveBlob,
  submitTeacherMetadata,
} from "../lib/memoService";
import { reviewUrl } from "../lib/urls";
import { DocumentDetails } from "./DocumentDetails";

const POLL_MS = 6000;

export function ConversionProgress({ client, user, initialJob, onBack }) {
  const [job, setJob] = useState(initialJob);
  const [state, setState] = useState({ busy: "", error: "" });
  const [metadataDetails, setMetadataDetails] = useState(null);
  const status = teacherStatus(job);
  const metadataReview = job?.status === "needs_review" &&
    job?.stage === "phase8_1b_metadata_review";

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

  useEffect(() => {
    if (!metadataReview && job?.status !== "complete") return undefined;
    let active = true;
    fetchCanonicalMetadata(client, user.id, job.id)
      .then((details) => { if (active) setMetadataDetails(details); })
      .catch((error) => {
        if (active && metadataReview) {
          setState((current) => ({ ...current, error: error.message }));
        }
      });
    return () => { active = false; };
  }, [client, job?.id, job?.status, metadataReview, user.id]);

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

  async function applyMetadata(teacherMetadata) {
    setState({ busy: "metadata", error: "" });
    try {
      await submitTeacherMetadata(client, job.id, teacherMetadata);
      await refresh();
      setState({ busy: "", error: "" });
    } catch (error) {
      setState({ busy: "", error: error.message });
    }
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

  const missingMetadata = metadataDetails
    ? ["grade_label", "duration_minutes"].filter(
      (field) => metadataDetails.effective?.[field] == null &&
        !metadataDetails.provenance?.[field]?.confirmed_absent
    )
    : [];

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

        {metadataReview && (
          <div className="action-card review-card">
            <h2>Document details need attention</h2>
            <p>The source does not state one or more cover details. Enter only what you know, or deliberately leave a field blank.</p>
            {metadataDetails ? (
              <DocumentDetails
                mode="review"
                teacherMetadata={job.teacher_metadata}
                effectiveMetadata={metadataDetails.effective}
                provenance={metadataDetails.provenance}
                missingFields={missingMetadata}
                onSubmit={applyMetadata}
                busy={state.busy === "metadata"}
              />
            ) : <p>Loading document details…</p>}
          </div>
        )}

        {canReview(job) && !metadataReview && (
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
            <details className="completed-metadata">
              <summary>Document details</summary>
              {metadataDetails ? (
                <DocumentDetails
                  mode="readonly"
                  effectiveMetadata={metadataDetails.effective}
                  provenance={metadataDetails.provenance}
                />
              ) : <p>Loading document details…</p>}
            </details>
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
