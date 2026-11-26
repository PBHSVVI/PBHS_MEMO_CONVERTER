"""Turn a proven failed, unclaimed Process Memo dispatch into a safe retry."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any

from .http import SupabaseRest
from .ingestion import validate_source_path

REPOSITORY = "PBHSVVI/PBHS_MEMO_CONVERTER"
PROJECT_URL = "https://njrqiurqljwtuqrvguhj.supabase.co"
FAILED_CONCLUSIONS = {"failure", "timed_out", "cancelled"}
JOB_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
RUN_NAME_PREFIX = "Process Memo "


class RecoveryRejected(RuntimeError):
    """Safe diagnostic when a run cannot be bound to an unclaimed dispatch."""


def _github(*args: str) -> str:
    # Never relay stderr or the full log, which may contain private diagnostics.
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, encoding="utf-8", timeout=60
    ).stdout


def _verify_legacy_run(run_id: str, requested_job: str) -> None:
    # Older workflows used a generic run title. Require the skipped worker and
    # the original finalizer's job-specific receipt from that exact run.
    jobs = json.loads(_github("api", f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs"))["jobs"]
    for job in jobs:
        steps = {step["name"]: step["conclusion"] for step in job["steps"]}
        if (
            job["name"] == "process"
            and steps.get("Validate workflow input") == "success"
            and steps.get("Run hosted memo worker") == "skipped"
            and steps.get("Recover interrupted hosted worker") == "success"
        ):
            log = _github("run", "view", run_id, "--job", str(job["id"]), "--log", "-R", REPOSITORY)
            receipt = f"Worker finalizer left terminal job {requested_job} unchanged."
            if any(
                re.fullmatch(r"process\tRecover interrupted hosted worker\t\S+ " + re.escape(receipt), line)
                for line in log.splitlines()
            ):
                return
    raise RecoveryRejected("The legacy run does not prove the job identity and skipped worker.")


def failed_run_job(run: dict[str, Any], run_id: str, requested_job: str = "") -> str:
    if (
        str(run.get("id")) != run_id
        or run.get("path") != ".github/workflows/process-memo.yml"
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("head_repository", {}).get("full_name") != REPOSITORY
        or run.get("repository", {}).get("full_name") != REPOSITORY
        or run.get("run_attempt") != 1
        or run.get("status") != "completed"
        or run.get("conclusion") not in FAILED_CONCLUSIONS
    ):
        raise RecoveryRejected("The selected run is not an original failed Process Memo dispatch on main.")

    title = run.get("display_title", "")
    job_id = title.removeprefix(RUN_NAME_PREFIX)
    if title.startswith(RUN_NAME_PREFIX) and JOB_ID.fullmatch(job_id):
        if requested_job and job_id != requested_job:
            raise RecoveryRejected("The run does not match the requested job.")
        return job_id
    if title == "Process Memo" and JOB_ID.fullmatch(requested_job):
        _verify_legacy_run(run_id, requested_job)
        return requested_job
    raise RecoveryRejected("The failed run has no verifiable memo job identity.")


def recover_unclaimed_dispatch(
    db: SupabaseRest,
    job_id: str,
    run: dict[str, Any],
    expected_source_sha256: str = "",
) -> bool:
    job = db.get_job(job_id)
    if job["status"] != "dispatched" or job["stage"] != "dispatch" or not job.get("dispatched_at"):
        return False

    dispatched = dt.datetime.fromisoformat(job["dispatched_at"])
    created = dt.datetime.fromisoformat(run["created_at"])
    finished = dt.datetime.fromisoformat(run["updated_at"])
    # GitHub reports whole seconds. The run must already have been created
    # before a later dispatch could have replaced this attempt.
    dispatch_second = dispatched.replace(microsecond=0)
    if not created - dt.timedelta(minutes=5) <= dispatch_second <= created < finished:
        return False
    if job["started_at"] and dt.datetime.fromisoformat(job["started_at"]) >= dispatched:
        return False

    if expected_source_sha256:
        if not re.fullmatch(r"[a-f0-9]{64}", expected_source_sha256):
            raise RecoveryRejected("The expected source SHA-256 is invalid.")
        if job["attempt_count"] != 1 or job["started_at"] is not None or job.get("source_sha256"):
            raise RecoveryRejected("Source verification requires the original never-started dispatch.")
        source = db.download_object("memo-files", validate_source_path(job))
        if len(source) != job["source_size_bytes"] or hashlib.sha256(source).hexdigest() != expected_source_sha256:
            raise RecoveryRejected("The stored memo did not match its expected size and digest.")
        print(f"Stored source verified: {len(source)} bytes; SHA-256 matched.")

    stage = "worker_startup_failed"
    code = "WORKER_STARTUP_FAILED"
    failed = db.fail_unclaimed_dispatch(job, {
        "status": "failed_retryable",
        "stage": stage,
        "review_required": False,
        "error_code": code,
        "error_message": "Conversion could not start. Your memo is saved and can be retried.",
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    if not failed:
        return False
    db.add_event(failed, "worker_startup_failed", stage, {
        "error_code": code,
        "workflow_run_id": run["id"],
        "attempt_count": job["attempt_count"],
    })
    return True


def main() -> int:
    try:
        run_id = os.environ["FAILED_RUN_ID"]
        requested_job = os.environ.get("RECOVERY_JOB_ID", "")
        if not re.fullmatch(r"[1-9][0-9]{0,19}", run_id):
            raise RecoveryRejected("Invalid workflow run ID.")
        run = json.loads(_github("api", f"repos/{REPOSITORY}/actions/runs/{run_id}"))
        job_id = failed_run_job(run, run_id, requested_job)
        db = SupabaseRest()
        if db.base != PROJECT_URL:
            raise RecoveryRejected("The configured project is not the PBHS production project.")
        if recover_unclaimed_dispatch(db, job_id, run, os.environ.get("RECOVERY_SOURCE_SHA256", "")):
            print("The failed startup was recorded. The original memo is ready for authenticated retry.")
            return 0
        print("No matching unclaimed dispatch remains. No job state changed.")
        return 1 if requested_job else 0
    except RecoveryRejected as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print("Dispatch recovery could not verify or record the transition. Check the job state before retrying.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
