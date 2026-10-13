from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "20261013121004_temporary_first_login_password.sql"
FUNCTION = ROOT / "supabase" / "functions" / "complete-first-login" / "index.ts"
APP = ROOT / "web" / "src" / "App.jsx"
GATE = ROOT / "web" / "src" / "components" / "MandatoryPasswordChange.jsx"
PROVISIONING = ROOT / "web" / "scripts" / "staffProvisioning.mjs"
CLI = ROOT / "web" / "scripts" / "provision-staff.mjs"
GITIGNORE = ROOT / ".gitignore"


def test_server_controlled_flag_and_status_expose_no_authorization_fields():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "must_change_password boolean not null default false" in sql
    assert "create or replace function public.pbhs_first_login_status()" in sql
    status = sql[sql.index("create or replace function public.pbhs_first_login_status()") :]
    status = status[: status.index("create or replace function public.pbhs_complete_initial_password_change")]
    assert "password_change_required" in status
    assert "unavailable" in status
    assert "returns text" in status
    assert "display_name" not in status
    assert "hod_scope" not in status


def test_all_normal_browser_data_surfaces_require_completed_first_login():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "and not p.must_change_password" in sql
    for policy in (
        "jobs_select_own",
        "jobs_insert_own",
        "job_events_select_own",
        "exceptions_select_own",
        "corrections_select_own",
        "corrections_insert_own",
        "memo_files_select_own",
        "memo_files_insert_own_inputs",
        "memo_files_update_own_inputs",
        "memo_files_delete_own_inputs",
        "support_incidents_insert_own",
        "support_incidents_select_own",
    ):
        marker = f'create policy "{policy}"'
        assert marker in sql
        block = sql[sql.index(marker) :]
        block = block[: block.index(";")]
        assert "memo_private.is_active_department_member()" in block


def test_completion_capability_is_service_only_and_password_update_happens_first():
    sql = MIGRATION.read_text(encoding="utf-8")
    source = FUNCTION.read_text(encoding="utf-8")
    assert "revoke all on function public.pbhs_complete_initial_password_change(uuid)" in sql
    assert "from public, anon, authenticated" in sql
    assert "grant execute on function public.pbhs_complete_initial_password_change(uuid)" in sql
    assert "to service_role" in sql
    assert 'withSupabase({ auth: "user" }' in source
    assert source.index('fetch(`${projectUrl}/auth/v1/user`') < source.index('rpc("pbhs_complete_initial_password_change"')
    assert '.eq("user_id", identity.user.id)' in source
    assert "console." not in source


def test_frontend_gate_precedes_every_workspace_surface():
    app = APP.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    assert app.index("FIRST_LOGIN.PASSWORD_CHANGE_REQUIRED") < app.index('const user = auth.session.user')
    assert "Choose your private password" in gate
    assert "Set my password" in gate
    assert 'completeFirstLogin(client, password)' in gate
    assert 'await client.auth.signOut({ scope: "local" })' in gate


def test_temporary_provisioning_is_explicit_and_runtime_only():
    source = PROVISIONING.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    assert '"--temporary-password"' in cli
    assert 'rawInput?.staff_code' in cli
    assert '"staff_code"' in source
    assert "temporary_password_supplied" in source
    assert "setTemporaryPassword" in source
    assert "setMustChangePassword" in source
    assert "provisioning-private/" in GITIGNORE.read_text(encoding="utf-8")


def test_scanner_safe_otp_architecture_remains_present():
    assert (ROOT / "supabase" / "migrations" / "0009_scanner_safe_onboarding.sql").exists()
    assert (ROOT / "supabase" / "templates" / "pbhs_setup_otp.html").exists()
    onboarding = (ROOT / "web" / "src" / "components" / "InviteOnboarding.jsx").read_text(encoding="utf-8")
    assert "requestSetupCode" in onboarding
    assert "verifySetupCode" in onboarding
