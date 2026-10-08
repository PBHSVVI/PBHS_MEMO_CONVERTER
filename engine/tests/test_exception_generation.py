from __future__ import annotations

import pytest

from engine.src.memo_engine.http import SupabaseRest


JOB = {"id": "job-1", "user_id": "user-1"}
FINDING = {
    "level": "amber",
    "category": "item_total_mismatch",
    "affected_id": "5.1",
    "message": "sanitized finding",
    "suggestions": [],
}


def _client(calls, *, fail_insert=False):
    client = object.__new__(SupabaseRest)

    def request(method, path, *, body=None, prefer=None):
        calls.append((method, path, body, prefer))
        if fail_insert and method == "POST":
            raise RuntimeError("insert failed")
        return []

    client._request_json = request
    return client


def test_new_generation_is_inserted_before_old_rows_are_superseded():
    calls = []
    _client(calls).replace_unresolved_exception_generation(JOB, [FINDING])

    assert calls[0][0:2] == ("POST", "/rest/v1/exceptions")
    new_id = calls[0][2][0]["id"]
    patches = calls[1:]
    assert len(patches) == 3
    assert all(call[0] == "PATCH" for call in patches)
    assert all(f"id=not.in.({new_id})" in call[1] for call in patches)


def test_failed_new_generation_insert_preserves_previous_review_generation():
    calls = []
    with pytest.raises(RuntimeError, match="insert failed"):
        _client(calls, fail_insert=True).replace_unresolved_exception_generation(JOB, [FINDING])

    assert len(calls) == 1
    assert calls[0][0] == "POST"


def test_successful_empty_generation_supersedes_previous_active_rows():
    calls = []
    _client(calls).replace_unresolved_exception_generation(JOB, [])

    assert len(calls) == 3
    assert all(call[0] == "PATCH" for call in calls)
    assert all("id=not.in." not in call[1] for call in calls)


def test_cli_replaces_generation_after_all_validation_has_computed():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "memo_engine" / "cli.py").read_text(encoding="utf-8")
    replace_at = source.index("db.replace_unresolved_exception_generation")
    canonical_at = source.index("canonical, validation, canonical_exceptions = build_canonical_memo")
    assert replace_at > canonical_at
    assert "db.add_exceptions(job, structural_exceptions)" not in source
    assert "db.add_exceptions(job, semantic_exceptions)" not in source
    assert "db.supersede_unresolved_exceptions(job_id)" not in source


def test_metadata_only_rerun_replaces_40_active_rows_with_39_current_rows():
    state = [
        {"id": f"old-{index}", "status": "open"}
        for index in range(40)
    ]
    client = object.__new__(SupabaseRest)

    def request(method, path, *, body=None, prefer=None):
        if method == "POST":
            state.extend(dict(row) for row in body)
            return []
        if method == "PATCH":
            status_value = path.split("status=eq.", 1)[1].split("&", 1)[0]
            excluded = set()
            if "id=not.in.(" in path:
                excluded = set(path.split("id=not.in.(", 1)[1].split(")", 1)[0].split(","))
            for row in state:
                if row["status"] == status_value and row["id"] not in excluded:
                    row.update(body)
            return []
        raise AssertionError((method, path))

    client._request_json = request
    client.replace_unresolved_exception_generation(JOB, [dict(FINDING) for _ in range(39)])

    active = [row for row in state if row["status"] == "open"]
    assert len(active) == 39
    assert all(not row["id"].startswith("old-") for row in active)
