from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from engine.src.memo_engine import dispatch_recovery as recovery
from engine.src.memo_engine.http import SupabaseRest


JOB = "12345678-1234-4123-8123-123456789abc"
RUN = {
    "id": 123,
    "path": ".github/workflows/process-memo.yml",
    "event": "workflow_dispatch",
    "head_branch": "main",
    "head_repository": {"full_name": recovery.REPOSITORY},
    "repository": {"full_name": recovery.REPOSITORY},
    "run_attempt": 1,
    "status": "completed",
    "conclusion": "failure",
    "display_title": f"Process Memo {JOB}",
    "created_at": "2026-11-26T05:23:22Z",
    "updated_at": "2026-11-26T05:24:50Z",
}


class FakeDatabase:
    def __init__(self, **overrides):
        self.job = {
            "id": JOB,
            "user_id": "owner",
            "status": "dispatched",
            "stage": "dispatch",
            "attempt_count": 1,
            "started_at": None,
            "dispatched_at": "2026-11-26T05:23:20.624+00:00",
            "source_path": f"owner/{JOB}/source/source.pdf",
            "source_size_bytes": 4,
            **overrides,
        }
        self.events = []
        self.downloads = []

    def get_job(self, job_id):
        assert job_id == JOB
        return dict(self.job)

    def fail_unclaimed_dispatch(self, observed, update):
        if observed != self.job:
            return None
        self.job.update(update)
        return self.job

    def add_event(self, _job, event, stage, payload):
        self.events.append((event, stage, payload))

    def download_object(self, bucket, path):
        self.downloads.append((bucket, path))
        return b"memo"


def test_completed_failed_run_recovers_original_dispatch_once_and_verifies_source():
    db = FakeDatabase()
    assert recovery.failed_run_job(RUN, "123") == JOB
    assert recovery.recover_unclaimed_dispatch(db, JOB, RUN, hashlib.sha256(b"memo").hexdigest())
    assert db.downloads == [("memo-files", f"owner/{JOB}/source/source.pdf")]
    assert (db.job["status"], db.job["stage"]) == ("failed_retryable", "worker_startup_failed")
    assert db.job["review_required"] is False
    assert db.job["attempt_count"] == 1 and db.job["started_at"] is None
    assert db.events == [("worker_startup_failed", "worker_startup_failed", {
        "error_code": "WORKER_STARTUP_FAILED", "workflow_run_id": 123, "attempt_count": 1,
    })]
    assert not recovery.recover_unclaimed_dispatch(db, JOB, RUN)
    assert len(db.events) == 1


@pytest.mark.parametrize("overrides", [
    {"status": "processing", "stage": "normalization"},
    {"status": "failed_retryable", "stage": "worker_failed"},
    {"status": "needs_review", "stage": "phase5_canonicalized"},
    {"attempt_count": 2, "dispatched_at": "2026-11-26T05:24:51Z"},
    {"started_at": "2026-11-26T05:23:23Z"},
    {"dispatched_at": "2026-11-26T05:10:00Z"},
])
def test_recovery_leaves_active_finished_and_other_attempts_untouched(overrides):
    db = FakeDatabase(**overrides)
    assert not recovery.recover_unclaimed_dispatch(db, JOB, RUN)
    assert not db.events and not db.downloads


@pytest.mark.parametrize("field,value", [
    ("path", ".github/workflows/other.yml"),
    ("head_branch", "feature"),
    ("run_attempt", 2),
    ("conclusion", "success"),
    ("status", "in_progress"),
])
def test_recovery_rejects_untrusted_incomplete_and_successful_runs(field, value):
    with pytest.raises(recovery.RecoveryRejected):
        recovery.failed_run_job({**RUN, field: value}, "123", JOB)


def test_named_run_cannot_recover_another_job():
    with pytest.raises(recovery.RecoveryRejected, match="does not match"):
        recovery.failed_run_job(RUN, "123", "87654321-1234-4123-8123-123456789abc")


def test_legacy_run_requires_exact_job_receipt_and_skipped_worker(monkeypatch):
    steps = [
        {"name": "Validate workflow input", "conclusion": "success"},
        {"name": "Run hosted memo worker", "conclusion": "skipped"},
        {"name": "Recover interrupted hosted worker", "conclusion": "success"},
    ]
    log = f"process\tRecover interrupted hosted worker\t2026-11-26T05:24:46Z Worker finalizer left terminal job {JOB} unchanged."
    monkeypatch.setattr(recovery, "_github", lambda command, *_: (
        json.dumps({"jobs": [{"name": "process", "id": 321, "steps": steps}]}) if command == "api" else log
    ))
    legacy_run = {**RUN, "display_title": "Process Memo"}
    assert recovery.failed_run_job(legacy_run, "123", JOB) == JOB
    with pytest.raises(recovery.RecoveryRejected):
        recovery.failed_run_job(legacy_run, "123", "87654321-1234-4123-8123-123456789abc")
    steps[1]["conclusion"] = "failure"
    with pytest.raises(recovery.RecoveryRejected):
        recovery.failed_run_job(legacy_run, "123", JOB)


def test_mismatched_source_refuses_state_change():
    db = FakeDatabase()
    with pytest.raises(recovery.RecoveryRejected, match="size and digest"):
        recovery.recover_unclaimed_dispatch(db, JOB, RUN, "a" * 64)
    assert db.job["status"] == "dispatched" and not db.events


def test_rest_compare_and_set_guards_against_concurrent_worker_or_retry(monkeypatch):
    db = object.__new__(SupabaseRest)

    def rejected_patch(method, path, *, body, prefer):
        assert method == "PATCH" and prefer == "return=representation"
        assert body == {"status": "failed_retryable"}
        # PostgREST must check both the unclaimed state and the precise attempt.
        assert parse_qs(urlsplit(path).query) == {
            "id": [f"eq.{JOB}"], "status": ["eq.dispatched"], "stage": ["eq.dispatch"],
            "attempt_count": ["eq.1"], "started_at": ["is.null"],
            "dispatched_at": ["eq.2026-11-26T05:23:20.624+00:00"],
        }
        return []

    monkeypatch.setattr(db, "_request_json", rejected_patch)
    assert db.fail_unclaimed_dispatch(FakeDatabase().job, {"status": "failed_retryable"}) is None
