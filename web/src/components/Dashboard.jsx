import { useCallback, useEffect, useMemo, useState } from "react";
import { canDownload, canReview, canRetry, teacherStatus } from "../lib/jobContracts";
import { listDepartmentPapers, listRecentJobs } from "../lib/memoService";
import {
  DEPARTMENTS,
  FORMS,
  PAPER_SCOPES,
  WORK_STATES,
  filterPapers,
  ownerJobPaper,
  paperContext,
  paperIdentity,
  papersForScope,
  unclassifiedOwnerPapers,
} from "../lib/paperWorkspace";

const DEPARTMENT_SESSION_KEY = "pbhs.workspace.department";

function initialDepartment() {
  try {
    const saved = sessionStorage.getItem(DEPARTMENT_SESSION_KEY);
    return DEPARTMENTS.some(({ value }) => value === saved) ? saved : "mathematics";
  } catch {
    return "mathematics";
  }
}

function actionLabel(job) {
  if (canReview(job)) return "Review";
  if (canDownload(job)) return "Open";
  if (canRetry(job)) return "Retry";
  return "Continue";
}

function PaperCard({ paper, onOpen }) {
  const status = teacherStatus({ status: paper.status_source, stage: paper.stage_source });
  const context = paperContext(paper);
  const updated = paper.updated_at
    ? new Intl.DateTimeFormat("en-ZA", { dateStyle: "medium", timeStyle: "short" }).format(new Date(paper.updated_at))
    : null;
  return (
    <article className="paper-card">
      <div className="paper-card__identity">
        <span className={`status-pill ${status.tone}`}>{status.label}</span>
        <h3>{paperIdentity(paper)}</h3>
        {context.length > 0 && <p className="paper-context">{context.join(" · ")}</p>}
        {paper.source_filename && paperIdentity(paper) !== paper.source_filename && (
          <p className="paper-filename">{paper.source_filename}</p>
        )}
      </div>
      <dl className="paper-card__details">
        {paper.owner_display_name && <><dt>Owner</dt><dd>{paper.owner_display_name}</dd></>}
        {updated && <><dt>Updated</dt><dd>{updated}</dd></>}
      </dl>
      <div className="paper-card__action">
        {paper.owner_job ? (
          <button className={`button ${canReview(paper.owner_job) ? "review" : "secondary"}`} onClick={() => onOpen(paper.owner_job)}>
            {actionLabel(paper.owner_job)}
          </button>
        ) : (
          <span className="department-entry">Department paper</span>
        )}
      </div>
    </article>
  );
}

function Selector({ className, label, options, value, onChange, counts = {} }) {
  return (
    <div className={className} aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={value === option.value ? "selected" : ""}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          <span>{option.label}</span>
          {Number.isInteger(counts[option.value]) && <small>{counts[option.value]}</small>}
        </button>
      ))}
    </div>
  );
}

export function Dashboard({ client, user, onConvert, onOpen }) {
  const [ownerJobs, setOwnerJobs] = useState([]);
  const [libraryRows, setLibraryRows] = useState([]);
  const [state, setState] = useState({ loading: true, error: "", libraryUnavailable: false });
  const [department, setDepartment] = useState(initialDepartment);
  const [workState, setWorkState] = useState("in_progress");
  const [scope, setScope] = useState("my");
  const [form, setForm] = useState(1);

  const load = useCallback(async () => {
    setState({ loading: true, error: "", libraryUnavailable: false });
    const [jobsResult, libraryResult] = await Promise.allSettled([
      listRecentJobs(client, 100),
      listDepartmentPapers(client),
    ]);
    if (jobsResult.status === "rejected") {
      setState({ loading: false, error: jobsResult.reason.message, libraryUnavailable: libraryResult.status === "rejected" });
      return;
    }
    setOwnerJobs(jobsResult.value);
    setLibraryRows(libraryResult.status === "fulfilled" ? libraryResult.value : []);
    setState({ loading: false, error: "", libraryUnavailable: libraryResult.status === "rejected" });
  }, [client]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    try { sessionStorage.setItem(DEPARTMENT_SESSION_KEY, department); } catch { /* session persistence is optional */ }
  }, [department]);

  const ownerPapers = useMemo(() => ownerJobs.map((job) => ownerJobPaper(job, user)), [ownerJobs, user]);
  const scopedPapers = useMemo(
    () => papersForScope({ scope, ownerPapers, libraryRows, ownerId: user.id }),
    [scope, ownerPapers, libraryRows, user.id],
  );
  const selectedPapers = useMemo(
    () => filterPapers(scopedPapers, { department, workState, scope, form, ownerId: user.id }),
    [scopedPapers, department, workState, scope, form, user.id],
  );
  const incompleteOwnerPapers = useMemo(
    () => scope === "my" ? unclassifiedOwnerPapers(ownerPapers, { ownerId: user.id, workState }) : [],
    [scope, ownerPapers, user.id, workState],
  );
  const formCounts = useMemo(() => Object.fromEntries(FORMS.map((number) => [
    number,
    filterPapers(scopedPapers, { department, workState, scope, form: number, ownerId: user.id }).length,
  ])), [scopedPapers, department, workState, scope, user.id]);
  const workCounts = useMemo(() => Object.fromEntries(WORK_STATES.map(({ value }) => [
    value,
    scopedPapers.filter((paper) => paper.subject_scope === department && paper.workflow_bucket === value).length,
  ])), [scopedPapers, department]);
  const departmentLabel = DEPARTMENTS.find(({ value }) => value === department)?.label || "Mathematics";
  const formLabel = `Form ${form}`;
  const profileHint = Boolean(user?.app_metadata?.pbhs_display_name);
  const allUnavailable = scope === "all" && (state.libraryUnavailable || (!profileHint && libraryRows.length === 0));

  function chooseDepartment(value) {
    setDepartment(value);
    setForm(1);
  }

  return (
    <main className="page-shell department-workspace">
      <section className="workspace-intro">
        <div>
          <p className="eyebrow">Department workspace</p>
          <h1>Mathematics papers</h1>
          <p>Continue work in progress or open completed departmental papers.</p>
        </div>
        <button className="button primary" onClick={() => onConvert({ department, form })}>Upload memo</button>
      </section>

      <section className="workspace-controls" aria-label="Paper filters">
        <div className="control-group department-control">
          <span className="control-label">Department</span>
          <Selector className="department-selector" label="Department" options={DEPARTMENTS} value={department} onChange={chooseDepartment} />
        </div>
        <div className="workspace-filter-row">
          <div className="control-group">
            <span className="control-label">Work state</span>
            <Selector className={`state-selector state-selector--${workState}`} label="Work state" options={WORK_STATES} value={workState} onChange={setWorkState} counts={workCounts} />
          </div>
          <div className="control-group">
            <span className="control-label">Quick filter</span>
            <Selector className="scope-selector" label="Paper ownership" options={PAPER_SCOPES} value={scope} onChange={setScope} />
          </div>
          <button className="button quiet refresh-action" onClick={load} disabled={state.loading}>Refresh</button>
        </div>
      </section>

      <section className="paper-workspace" aria-labelledby="paper-list-title">
        <div className="form-tabs" role="tablist" aria-label="Form">
          {FORMS.map((number) => (
            <button key={number} role="tab" aria-selected={form === number} className={form === number ? "selected" : ""} onClick={() => setForm(number)}>
              <span>Form {number}</span><small>{formCounts[number]}</small>
            </button>
          ))}
        </div>
        <div className="paper-list-heading">
          <div>
            <p className="eyebrow">{scope === "all" ? "Department library" : "My papers"}</p>
            <h2 id="paper-list-title">{formLabel} · {departmentLabel}</h2>
          </div>
          <span className={`work-state-label ${workState}`}>{workState === "completed" ? "Completed" : "In progress"}</span>
        </div>

        {state.error && <p className="notice danger" role="alert">{state.error}</p>}
        {state.loading ? (
          <p className="empty-state">Loading papers…</p>
        ) : allUnavailable ? (
          <div className="empty-state library-unavailable">
            <h3>Your department library access has not been activated yet.</h3>
            <p>You can continue using My papers for work owned by your account.</p>
            <button className="button secondary" onClick={() => setScope("my")}>Show my papers</button>
          </div>
        ) : selectedPapers.length ? (
          <div className="paper-list">{selectedPapers.map((paper) => <PaperCard key={paper.job_id} paper={paper} onOpen={onOpen} />)}</div>
        ) : (
          <div className="empty-state">
            <h3>No {workState === "completed" ? "completed" : "in-progress"} {formLabel} {departmentLabel} papers.</h3>
            <p>{scope === "all" ? "Department papers will appear here when their safe summaries are available." : "Your matching conversions will appear here."}</p>
          </div>
        )}

        {!state.loading && incompleteOwnerPapers.length > 0 && (
          <details className="metadata-incomplete">
            <summary>Needs document details · {incompleteOwnerPapers.length} paper{incompleteOwnerPapers.length === 1 ? "" : "s"}</summary>
            <p>These uploads are safe, but we do not yet know which Form or department they belong to.</p>
            <div className="paper-list">{incompleteOwnerPapers.map((paper) => <PaperCard key={paper.job_id} paper={paper} onOpen={onOpen} />)}</div>
          </details>
        )}
      </section>
    </main>
  );
}
