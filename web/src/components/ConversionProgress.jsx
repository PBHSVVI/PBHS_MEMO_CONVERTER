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
  getLatestVisualProgress,
  retryJob,
  saveBlob,
  sourceObjectExists,
  submitTeacherMetadata,
} from "../lib/memoService";
import { reviewUrl } from "../lib/urls";
import { DocumentDetails } from "./DocumentDetails";
import { SupportIncident } from "./SupportIncident";

const POLL_MS = 6000;
const VISUAL_HEARTBEAT_DELAY_MS = 120000;
const NOOP = () => {};
const PROCESSING_STEPS = [
  "Reading your memo",
  "Checking question structure",
  "Interpreting the marking guideline",
  "Preparing your document",
  "Creating Word and PDF files",
];

const STAGE_STEP = {
  ingestion: 0,
  normalization: 0,
  visual_evidence: 0,
  structure: 1,
  semantic_interpretation: 2,
  canonicalization: 3,
  phase5_render_ready: 3,
  rendering: 4,
};

function elapsedLabel(job, now) {
  const started = new Date(job.started_at || job.created_at).getTime();
  const seconds = Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 1000)) : 0;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
}

export function ConversionProgress({ client, user, initialJob, onBack, onRevise = NOOP, onJobChange = NOOP }) {
  const [job, setJob] = useState(initialJob);
  const [state, setState] = useState({ busy: "", error: "" });
  const [metadataDetails, setMetadataDetails] = useState(null);
  const [sourceAvailable, setSourceAvailable] = useState(null);
  const [visualProgress, setVisualProgress] = useState(null);
  const [now, setNow] = useState(() => Date.now());
  const uploadedBeforeDispatch = job?.status === "queued" && job?.stage === "upload" && sourceAvailable === true;
  const status = teacherStatus(uploadedBeforeDispatch ? { ...job, stage: "dispatch_retry" } : job);
  const metadataReview = job?.status === "needs_review" &&
    job?.stage === "phase8_1b_metadata_review";

  const refresh = useCallback(async () => {
    try {
      const updated = await getJob(client, initialJob.id);
      setJob(updated);
      onJobChange(updated);
    } catch (error) {
      setState((current) => ({ ...current, error: error.message }));
    }
  }, [client, initialJob.id, onJobChange]);

  useEffect(() => {
    refresh();
    if (!ACTIVE_JOB_STATUSES.has(job?.status)) return undefined;
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [job?.status, refresh]);

  useEffect(() => {
    if (job?.status !== "processing" || job?.stage !== "visual_evidence") {
      setVisualProgress(null);
      return undefined;
    }
    let active = true;
    async function refreshVisualProgress() {
      try {
        const progress = await getLatestVisualProgress(client, job.id);
        if (active) setVisualProgress(progress);
      } catch (error) {
        if (active) setState((current) => ({ ...current, error: error.message }));
      }
    }
    refreshVisualProgress();
    const timer = window.setInterval(refreshVisualProgress, POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [client, job?.id, job?.stage, job?.status]);

  useEffect(() => {
    if (!ACTIVE_JOB_STATUSES.has(job?.status)) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [job?.status]);

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

  useEffect(() => {
    if (job?.status !== "queued" || job?.stage !== "upload") {
      setSourceAvailable(null);
      return undefined;
    }
    let active = true;
    sourceObjectExists(client, user.id, job).then((exists) => {
      if (active) setSourceAvailable(exists);
    });
    return () => { active = false; };
  }, [client, job?.id, job?.source_path, job?.stage, job?.status, user.id]);

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
      saveBlob(await fetchOutput(client, user.id, job, format));
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
  const processingStep = STAGE_STEP[job?.stage] ?? 0;
  const complete = canDownload(job);
  const visualHeartbeatAt = new Date(
    visualProgress?.created_at || job?.updated_at || job?.created_at
  ).getTime();
  const visualDelayed = job?.status === "processing" &&
    job?.stage === "visual_evidence" &&
    Number.isFinite(visualHeartbeatAt) && now - visualHeartbeatAt >= VISUAL_HEARTBEAT_DELAY_MS;
  const visualPayload = visualProgress?.payload || null;

  return (
    <main className="page-shell narrow">
      <button className="back-link" onClick={onBack}>← Recent conversions</button>
      <section className="panel progress-panel">
        <span className={`status-pill large ${status.tone}`}>{status.label}</span>
        {complete ? (
          <div className="completion-heading">
            <p className="eyebrow">Conversion complete</p>
            <h1>Ready</h1>
            <p className="completion-filename">{job.display_name || job.source_filename || "Converted memo"}</p>
          </div>
        ) : (
          <>
            <h1>{job.source_filename || "Memo conversion"}</h1>
            <p className="lede">{status.detail}</p>
          </>
        )}

        <div className={`progress-track${complete ? " complete" : ""}`} aria-label="Conversion progress">
          <span className={`progress-dot ${job.status === "complete" ? "done" : ""}`} />
          <div>
            <strong>{teacherStage(job)}</strong>
            {ACTIVE_JOB_STATUSES.has(job.status) ? (
              <p>Elapsed {elapsedLabel(job, now)}</p>
            ) : (
              <p>Updated {new Intl.DateTimeFormat("en-ZA", { dateStyle: "medium", timeStyle: "short" }).format(new Date(job.updated_at || job.created_at))}</p>
            )}
          </div>
        </div>

        {job?.status === "processing" && job?.stage === "visual_evidence" && (
          <div className="visual-progress" role="status" aria-live="polite">
            <strong>Reading visual annotations…</strong>
            {visualPayload?.region_index && visualPayload?.region_count ? (
              <span>
                Region {visualPayload.region_index} of {visualPayload.region_count}
                {visualPayload.page ? ` · Page ${visualPayload.page}` : ""}
              </span>
            ) : (
              <span>Preparing visual regions…</span>
            )}
          </div>
        )}

        {visualDelayed && (
          <div className="notice info visual-delay" role="alert">
            <strong>Visual reading is taking longer than expected.</strong>
            <p>Your uploaded memo and completed progress are saved. If processing pauses, the normal Retry conversion action will appear safely.</p>
            <SupportIncident client={client} user={user} label="Report delayed processing" context={{ job, currentView: "visual_processing_delayed", visualProgress }} />
          </div>
        )}

        {ACTIVE_JOB_STATUSES.has(job.status) && (
          <ol className="progress-steps" aria-label="Conversion stages">
            {PROCESSING_STEPS.map((step, index) => (
              <li key={step} className={index < processingStep ? "done" : index === processingStep ? "current" : ""} aria-current={index === processingStep ? "step" : undefined}>{step}</li>
            ))}
          </ol>
        )}

        {state.error && <p className="notice danger" role="alert">{state.error}</p>}
        {state.error && <SupportIncident client={client} user={user} label="Report this error" context={{ job, currentView: "conversion_error" }} />}

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

        {complete && (
          <div className="action-card success-card completion-card">
            <div className="button-row">
              <button className="button primary" onClick={() => download("docx")} disabled={Boolean(state.busy)}>
                {state.busy === "docx" ? "Downloading…" : "Download Word"}
              </button>
              <button className="button secondary" onClick={() => download("pdf")} disabled={Boolean(state.busy)}>
                {state.busy === "pdf" ? "Downloading…" : "Download PDF"}
              </button>
            </div>
            <button className="button quiet revise-action" onClick={onRevise}>Create revised conversion</button>
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

        {(canRetry(job) || uploadedBeforeDispatch) && (
          <div className="action-card danger-card">
            <h2>Conversion paused safely</h2>
            <p>Your original memo and any confirmed review decisions are still saved. You can retry this conversion.</p>
            <button className="button primary" onClick={retry} disabled={state.busy === "retry"}>
              {state.busy === "retry" ? "Retrying…" : "Retry conversion"}
            </button>
            <SupportIncident client={client} user={user} label="Report this error" context={{ job, currentView: "retryable_failure" }} />
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
            <SupportIncident client={client} user={user} label="Report this error" context={{ job, currentView: "conversion_failed" }} />
            {job.error_code && (
              <details className="technical">
                <summary>Technical details</summary>
                <code>{job.error_code}</code>
              </details>
            )}
          </div>
        )}

        {ACTIVE_JOB_STATUSES.has(job.status) && (
          <p className="poll-note">You can safely leave this page and return later. Progress is saved automatically.</p>
        )}
      </section>
    </main>
  );
}
