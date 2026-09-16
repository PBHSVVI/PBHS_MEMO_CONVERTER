from __future__ import annotations

import datetime as dt
import sys

from .http import SupabaseRest


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_job(job_id: str) -> int:
    db = SupabaseRest()
    job = db.get_job(job_id)

    if job["status"] != "dispatched":
        raise RuntimeError(f"Job is not dispatchable from state {job['status']!r}")

    job = db.patch_job(
        job_id,
        "dispatched",
        {
            "status": "processing",
            "stage": "phase0",
            "started_at": utc_now(),
            "updated_at": utc_now(),
        },
    )
    db.add_event(job, "worker_started", "phase0")

    # Phase 0 proves hosted orchestration only.
    job = db.patch_job(
        job_id,
        "processing",
        {
            "status": "failed_retryable",
            "stage": "phase0_ready",
            "error_code": "PHASE0_ENGINE_NOT_YET_CONNECTED",
            "error_message": "Hosted runner and durable job transition succeeded; ingestion is the next milestone.",
            "updated_at": utc_now(),
        },
    )
    db.add_event(job, "phase0_runner_verified", "phase0_ready")
    print(f"Phase 0 runner verified for job {job_id}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "run-job":
        print("usage: python -m engine.src.memo_engine.cli run-job <job_id>", file=sys.stderr)
        return 2
    return run_job(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
