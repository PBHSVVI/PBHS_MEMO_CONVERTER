from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROVISIONING = ROOT / "web" / "scripts" / "staffProvisioning.mjs"
CLI = ROOT / "web" / "scripts" / "provision-staff.mjs"
APP = ROOT / "web" / "src" / "App.jsx"
ONBOARDING = ROOT / "web" / "src" / "components" / "InviteOnboarding.jsx"
DOC = ROOT / "docs" / "PHASE8_3B_STAFF_ONBOARDING.md"
OTP = ROOT / "web" / "src" / "lib" / "otpOnboarding.js"
MIGRATION = ROOT / "supabase" / "migrations" / "0009_scanner_safe_onboarding.sql"
TEMPLATE = ROOT / "supabase" / "templates" / "pbhs_setup_otp.html"


def test_provisioning_is_trusted_runtime_only_and_creates_no_raw_invite():
    source = PROVISIONING.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    assert 'request("/auth/v1/admin/users"' in source
    assert "email_confirm: true" in source
    assert "/auth/v1/admin/generate_link" not in source
    assert "department_profiles" in source
    assert "SUPABASE_SECRET_KEY" in cli
    assert "process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY" in cli
    assert "--dry-run" in cli
    assert "--input" in cli
    assert "--password" not in cli
    assert "password:" not in source.lower()
    assert "sb_secret_" in source


def test_hosted_validation_requires_modern_secret_without_legacy_fallback():
    harness = (ROOT / "web" / "scripts" / "validate-staff-onboarding-hosted.mjs").read_text(encoding="utf-8")
    assert "SUPABASE_SECRET_KEY: process.env.SUPABASE_SECRET_KEY" in harness
    assert "SUPABASE_SERVICE_ROLE_KEY" not in harness
    assert "redactSensitiveValue(safeResult)" in harness
    assert 'publishable?.startsWith("sb_publishable_")' in harness
    assert "scanner_gets_safe" in harness
    assert "otp_replay_denied" in harness
    assert "missing_profile_denied" in harness
    assert "inactive_profile_denied" in harness
    assert "unprovisioned_denied" in harness
    assert "normal_password_login" in harness
    assert "sensitive_output_redacted" in harness
    assert "modern_credentials_only" in harness


def test_safe_report_and_provisioning_exclude_invite_material():
    source = PROVISIONING.read_text(encoding="utf-8")
    assert "actionLink" not in source
    assert "generateInvite" not in source
    assert "RAW_INVITES_DISABLED" in source
    assert "action_link:" not in source
    report = source[source.index("export function safeProvisioningReport"):source.index("export async function provisionStaff")]
    assert "actionLink" not in report
    assert "password" not in report.lower()


def test_browser_has_code_onboarding_but_no_signup_path():
    app = APP.read_text(encoding="utf-8")
    onboarding = ONBOARDING.read_text(encoding="utf-8")
    assert "InviteOnboarding" in app
    assert "inviteRouteState" in app
    otp = OTP.read_text(encoding="utf-8")
    assert "client.auth.updateUser({ password })" in onboarding
    assert "await client.auth.signOut()" in onboarding
    assert "Create your PBHS Mathematics account" in onboarding
    assert "client.auth.signInWithOtp" in otp
    assert "shouldCreateUser: false" in otp
    assert "client.auth.verifyOtp" in otp
    assert 'type: "email"' in otp
    assert "signUp" not in app + onboarding


def test_profile_gate_exposes_only_boolean_active_membership():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "returns boolean" in sql
    assert "p.user_id = (select auth.uid())" in sql
    assert "and p.active" in sql
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "revoke all on function public.pbhs_active_profile_status() from public, anon" in sql
    assert "grant execute on function public.pbhs_active_profile_status() to authenticated" in sql


def test_auth_template_contains_code_and_no_consumable_auth_url():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "{{ .Token }}" in template
    assert "onboarding=setup" in template
    assert "{{ .ConfirmationURL }}" not in template
    assert "{{ .TokenHash }}" not in template
    assert "/auth/v1/verify" not in template


def test_documentation_records_free_plan_and_authorization_boundaries():
    text = DOC.read_text(encoding="utf-8")
    assert "Leaked Password Protection is unavailable" in text
    assert "department_profiles" in text
    assert "user_metadata" in text
    assert "No real PBHS staff" in text
    assert "institutional link scanning consumed Amanda's link" in text
    assert "Custom SMTP" in text
    assert "temporary password" not in text.lower()
