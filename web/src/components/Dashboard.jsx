import { useCallback, useEffect, useState } from "react";
import { canDownload, canReview, canRetry, teacherStatus } from "../lib/jobContracts";
import { listRecentJobs } from "../lib/memoService";

function JobCard({ job, onOpen }) {
  const state = teacherStatus(job);
  return (
    <article className="job-card">
      <div className="job-main">
        <span className={`status-pill ${state.tone}`}>{state.label}</span>
        <h3>{job.source_filename || "Untitled memo"}</h3>
        <p>{new Intl.DateTimeFormat("en-ZA", { dateStyle: "medium", timeStyle: "short" }).format(new Date(job.created_at))}</p>
      </div>
      <div className="job-action">
        <button className={`button ${canReview(job) ? "review" : "secondary"}`} onClick={() => onOpen(job)}>
          {canReview(job)
            ? "Review memo"
            : canDownload(job)
              ? "Download files"
              : canRetry(job)
                ? "Retry conversion"
                : "View progress"}
        </button>
      </div>
    </article>
  );
}

export function Dashboard({ client, onConvert, onOpen }) {
  const [jobs, setJobs] = useState([]);
  const [state, setState] = useState({ loading: true, error: "" });

  const load = useCallback(async () => {
    setState({ loading: true, error: "" });
    try {
      setJobs(await listRecentJobs(client));
      setState({ loading: false, error: "" });
    } catch (error) {
      setState({ loading: false, error: error.message });
    }
  }, [client]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <main className="page-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Teacher workspace</p>
          <h1>Convert a mathematics memo</h1>
          <p>Upload the memo, review only the decisions that need you, then download the finished Word and PDF files.</p>
        </div>
        <button className="button primary" onClick={onConvert}>Convert a memo</button>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Your work</p>
            <h2>Recent conversions</h2>
          </div>
          <button className="button quiet" onClick={load} disabled={state.loading}>Refresh</button>
        </div>
        {state.error && <p className="notice danger" role="alert">{state.error}</p>}
        {state.loading ? (
          <p className="empty-state">Loading recent conversions…</p>
        ) : jobs.length ? (
          <div className="job-list">{jobs.map((job) => <JobCard key={job.id} job={job} onOpen={onOpen} />)}</div>
        ) : (
          <div className="empty-state">
            <h3>No conversions yet</h3>
            <p>Your converted memos will appear here.</p>
          </div>
        )}
      </section>
    </main>
  );
}
