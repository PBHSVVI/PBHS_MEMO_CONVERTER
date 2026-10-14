from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "0008_support_incidents.sql"
SOURCE_FILENAME_MIGRATION = ROOT / "supabase" / "migrations" / "0010_support_incident_source_filename.sql"
FUNCTION = ROOT / "supabase" / "functions" / "notify-support-incident" / "index.ts"
REVIEW = ROOT / "docs" / "phase7-5-review" / "index.html"


def test_support_incident_rls_and_admin_boundaries():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "alter table public.support_incidents enable row level security" in sql
    assert 'to authenticated\nwith check' in sql
    assert "auth.uid()" in sql
    assert "grant select, insert on public.support_incidents to authenticated" in sql
    assert "grant select, insert, update on public.support_incidents to service_role" in sql
    assert "delete on public.support_incidents" not in sql
    assert "resolution_note" in sql and "resolved_at" in sql


def test_notification_is_server_side_and_incident_survives_missing_provider():
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'withSupabase({ auth: "user" }' in source
    assert 'notification_status: "unavailable"' in source
    assert 'email_provider_not_configured' in source
    assert 'https://api.resend.com/emails' in source
    assert "Memo content, credentials and session material are deliberately excluded" in source


def test_support_context_adds_only_a_bounded_source_filename():
    sql = SOURCE_FILENAME_MIGRATION.read_text(encoding="utf-8")
    source = FUNCTION.read_text(encoding="utf-8")
    assert "add column if not exists source_filename text" in sql
    assert "length(source_filename) <= 260" in sql
    assert 'line("Source file", incident.source_filename)' in source


def test_review_help_is_authenticated_and_does_not_mutate_workflow():
    source = REVIEW.read_text(encoding="utf-8")
    assert 'id="supportAction"' in source
    assert "support_incidents" in source
    assert "notify-support-incident" in source
    support_source = source[source.index("async function submitSupport"):source.index("$('#reviewLogin')")]
    for prohibited in ("resume-correction", "dispatch-memo", "corrections').update", "jobs').update", "location.href="):
        assert prohibited not in support_source
