from __future__ import annotations

from pathlib import Path

import pytest

from engine.src.memo_engine.http import SupabaseRest
from engine.src.memo_engine.library import (
    paper_library_summary,
    subject_scope,
    workflow_bucket,
)
from engine.src.memo_engine.metadata import resolve_document_metadata


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "0007_phase83a_department_library.sql"
CLI = ROOT / "engine" / "src" / "memo_engine" / "cli.py"


def _job(**changes):
    value = {
        "id": "11111111-1111-4111-8111-111111111111",
        "user_id": "22222222-2222-4222-8222-222222222222",
        "source_filename": "source.docx",
        "status": "processing",
        "stage": "canonicalization",
        "created_at": "2026-10-12T08:00:00+00:00",
        "updated_at": "2026-10-12T08:05:00+00:00",
        "completed_at": None,
    }
    value.update(changes)
    return value


def _canonical(metadata=None, computed=150):
    return {
        "document_metadata": metadata or {},
        "totals": {"computed": computed},
    }


def test_summary_uses_effective_resolved_metadata_and_keeps_absent_values_null():
    resolved = resolve_document_metadata(
        "MATHEMATICS PAPER 2 FORM 5 TIME: 3 HOURS 2026",
        {
            "schema_version": "1.0",
            "values": {"paper": "PAPER 1", "exam_type": "CLASS TEST"},
            "confirmed_absent": [],
        },
    )
    metadata = {
        **resolved["effective"],
        "expected_total_marks": None,
    }
    summary = paper_library_summary(_job(), _canonical(metadata))
    assert summary["subject_scope"] == "mathematics"
    assert summary["subject_display"] == "MATHEMATICS"
    assert summary["paper"] == "PAPER 2"  # source beats teacher fallback
    assert summary["assessment_type"] == "CLASS TEST"
    assert summary["grade_label"] == "FORM 5"
    assert summary["duration_minutes"] == 180
    assert summary["expected_total_marks"] is None
    assert summary["term"] is None
    assert summary["computed_total_marks"] == 150


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("MATHEMATICS", "mathematics"),
        (" fs mathematics ", "fs_mathematics"),
        (None, None),
        ("TECHNICAL MATHEMATICS", None),
        ("MATHEMATICS AND SCIENCE", None),
    ],
)
def test_subject_scope_is_explicit_and_fails_closed(subject, expected):
    assert subject_scope(subject) == expected


def test_workflow_bucket_only_treats_terminal_success_as_completed():
    for status in (
        "queued", "processing", "needs_review", "correction_pending",
        "rendering", "failed_retryable", "failed",
    ):
        assert workflow_bucket(status) == "in_progress"
    assert workflow_bucket("complete") == "completed"


def test_summary_upsert_is_one_row_per_job_and_uses_postgrest_conflict_merge(monkeypatch):
    client = object.__new__(SupabaseRest)
    calls = []
    monkeypatch.setattr(client, "_request_json", lambda *args, **kwargs: calls.append((args, kwargs)))
    first = paper_library_summary(_job(), _canonical({"subject": "MATHEMATICS"}))
    second = paper_library_summary(
        _job(status="complete", stage="complete", completed_at="2026-10-12T08:20:00+00:00"),
        _canonical({"subject": "MATHEMATICS"}),
    )
    client.upsert_paper_library_summary(first)
    client.upsert_paper_library_summary(second)
    assert all(call[0][0] == "POST" for call in calls)
    assert all("on_conflict=job_id" in call[0][1] for call in calls)
    assert all(call[1]["prefer"] == "resolution=merge-duplicates,return=minimal" for call in calls)
    assert first["job_id"] == second["job_id"]
    assert second["workflow_bucket"] == "completed"


def _can_write(*, active, role, hod_scope, caller, owner, subject):
    return bool(
        active
        and (
            caller == owner
            or (role == "hod" and hod_scope is not None and hod_scope == subject)
        )
    )


def _can_read(*, authenticated, active, subject):
    return bool(
        authenticated
        and active
        and subject in {"mathematics", "fs_mathematics"}
    )


@pytest.mark.parametrize(
    ("case", "authenticated", "active", "subject", "allowed"),
    [
        ("anonymous", False, False, "mathematics", False),
        ("non_department", True, False, "mathematics", False),
        ("inactive", True, False, "fs_mathematics", False),
        ("teacher_math", True, True, "mathematics", True),
        ("teacher_fs", True, True, "fs_mathematics", True),
        ("hod_math", True, True, "mathematics", True),
        ("hod_fs", True, True, "fs_mathematics", True),
        ("unresolved", True, True, None, False),
    ],
)
def test_department_library_read_matrix(case, authenticated, active, subject, allowed):
    assert _can_read(
        authenticated=authenticated,
        active=active,
        subject=subject,
    ) is allowed, case


@pytest.mark.parametrize(
    ("case", "active", "role", "scope", "caller", "owner", "subject", "allowed"),
    [
        ("non_department", False, "teacher", None, "a", "a", "mathematics", False),
        ("inactive", False, "hod", "mathematics", "a", "b", "mathematics", False),
        ("teacher_own_math", True, "teacher", None, "a", "a", "mathematics", True),
        ("teacher_other_math", True, "teacher", None, "a", "b", "mathematics", False),
        ("teacher_other_fs", True, "teacher", None, "a", "b", "fs_mathematics", False),
        ("math_hod_other_math", True, "hod", "mathematics", "a", "b", "mathematics", True),
        ("math_hod_other_fs", True, "hod", "mathematics", "a", "b", "fs_mathematics", False),
        ("math_hod_own_fs", True, "hod", "mathematics", "a", "a", "fs_mathematics", True),
        ("fs_hod_other_fs", True, "hod", "fs_mathematics", "a", "b", "fs_mathematics", True),
        ("fs_hod_other_math", True, "hod", "fs_mathematics", "a", "b", "mathematics", False),
        ("fs_hod_own_math", True, "hod", "fs_mathematics", "a", "a", "mathematics", True),
        ("unresolved_other", True, "hod", "mathematics", "a", "b", None, False),
    ],
)
def test_authorization_matrix(case, active, role, scope, caller, owner, subject, allowed):
    assert _can_write(
        active=active,
        role=role,
        hod_scope=scope,
        caller=caller,
        owner=owner,
        subject=subject,
    ) is allowed, case


def test_migration_enforces_read_and_write_contract_without_broadening_storage():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "create table if not exists public.department_profiles" in sql
    assert "create table if not exists public.paper_library_summary" in sql
    assert "job_id uuid primary key" in sql
    assert "owner_display_name text" in sql
    assert "create schema if not exists memo_private" in sql
    assert "(select memo_private.is_active_department_member())" in sql
    assert "subject_scope in ('mathematics', 'fs_mathematics')" in sql
    assert "create or replace function memo_private.can_write_paper(p_job_id uuid)" in sql
    assert "j.user_id = (select auth.uid())" in sql
    assert "p.hod_scope = s.subject_scope" in sql
    assert "p.active" in sql
    assert "set search_path = ''" in sql
    assert "revoke all on function memo_private.can_write_paper(uuid) from public, anon" in sql
    assert "storage.objects" not in sql
    assert "insert into public.department_profiles" not in sql
    assert "@" not in sql


def test_migration_establishes_department_table_grants_from_zero():
    sql_without_comments = "\n".join(
        line
        for line in MIGRATION.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )
    statements = [
        " ".join(statement.split()).lower()
        for statement in sql_without_comments.split(";")
        if statement.strip()
    ]
    profile_revoke = (
        "revoke all on public.department_profiles "
        "from public, anon, authenticated, service_role"
    )
    summary_revoke = (
        "revoke all on public.paper_library_summary "
        "from public, anon, authenticated, service_role"
    )
    profile_service_grant = (
        "grant select, insert, update on public.department_profiles to service_role"
    )
    summary_browser_grant = (
        "grant select on public.paper_library_summary to authenticated"
    )
    summary_service_grant = (
        "grant select, insert, update on public.paper_library_summary to service_role"
    )

    assert profile_revoke in statements
    assert summary_revoke in statements
    assert profile_service_grant in statements
    assert summary_browser_grant in statements
    assert summary_service_grant in statements
    assert statements.index(profile_revoke) < statements.index(profile_service_grant)
    assert statements.index(summary_revoke) < statements.index(summary_browser_grant)
    assert statements.index(summary_revoke) < statements.index(summary_service_grant)

    department_table_grants = [
        statement
        for statement in statements
        if statement.startswith("grant ")
        and (
            " on public.department_profiles " in statement
            or " on public.paper_library_summary " in statement
        )
    ]
    assert set(department_table_grants) == {
        profile_service_grant,
        summary_browser_grant,
        summary_service_grant,
    }
    for statement in department_table_grants:
        assert all(
            privilege not in statement
            for privilege in ("delete", "truncate", "references", "trigger")
        )


def test_worker_publishes_canonical_summary_for_review_rendering_and_completion():
    source = CLI.read_text(encoding="utf-8")
    call = "db.upsert_paper_library_summary(paper_library_summary(job, canonical))"
    assert source.count(call) == 4
    assert source.index(call) > source.index("db.upload_json(BUCKET, canonical_path, canonical)")
    review = source.index('"status": final_status')
    rendering = source.index('"stage": "rendering"')
    complete = source.index('"status": "complete"')
    positions = [index for index in range(len(source)) if source.startswith(call, index)]
    assert any(index > review for index in positions)
    assert any(index > rendering for index in positions)
    assert any(index > complete for index in positions)


def test_summary_contract_uses_the_safe_browser_relation_without_profile_access():
    service = (ROOT / "web" / "src" / "lib" / "memoService.js").read_text(encoding="utf-8")
    assert '.from("paper_library_summary")' in service
    assert "department_profiles" not in service


def test_filing_metadata_is_projected_for_department_library_without_rewriting_canonical():
    filing = {
        "schema_version": "1.0",
        "subject_scope": "fs_mathematics",
        "form": 4,
        "assessment_type": "class_test",
        "term": 3,
        "year": 2026,
        "assessment_number": {"applicability": "required", "value": 2},
        "paper": {"applicability": "not_applicable", "value": None},
        "duration": {"value": 2, "unit": "periods", "duration_minutes": None},
    }
    canonical = _canonical({"subject": "MATHEMATICS", "paper": "PAPER 1", "duration_minutes": 60})
    summary = paper_library_summary(_job(filing_metadata=filing, display_name="Form 4 Class Test 2 Term 3 2026"), canonical)
    assert canonical["document_metadata"]["subject"] == "MATHEMATICS"
    assert summary == {
        **summary,
        "subject_scope": "fs_mathematics",
        "subject_display": "FS MATHEMATICS",
        "assessment_type": "CLASS TEST",
        "assessment_number": 2,
        "paper": None,
        "grade_label": "FORM 4",
        "term": "TERM 3",
        "year": 2026,
        "duration_value": 2,
        "duration_unit": "periods",
        "duration_minutes": None,
        "display_name": "Form 4 Class Test 2 Term 3 2026",
    }
