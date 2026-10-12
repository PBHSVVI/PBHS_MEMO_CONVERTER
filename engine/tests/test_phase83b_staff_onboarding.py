from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROVISIONING = ROOT / "web" / "scripts" / "staffProvisioning.mjs"
CLI = ROOT / "web" / "scripts" / "provision-staff.mjs"
APP = ROOT / "web" / "src" / "App.jsx"
ONBOARDING = ROOT / "web" / "src" / "components" / "InviteOnboarding.jsx"
DOC = ROOT / "docs" / "PHASE8_3B_STAFF_ONBOARDING.md"


def test_provisioning_is_trusted_runtime_only_and_has_no_password_input():
    source = PROVISIONING.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    assert "/auth/v1/admin/generate_link" in source
    assert 'type: "invite"' in source
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
    assert "cross_owner_write_blocked" in harness
    assert "sensitive_output_redacted" in harness
    assert "modern_credentials_only" in harness


def test_invite_material_is_callback_only_and_safe_report_excludes_it():
    source = PROVISIONING.read_text(encoding="utf-8")
    assert "await onInvite(invitation.actionLink)" in source
    assert "action_link:" not in source
    report = source[source.index("export function safeProvisioningReport"):source.index("export async function provisionStaff")]
    assert "actionLink" not in report
    assert "password" not in report.lower()


def test_browser_has_invite_onboarding_but_no_signup_path():
    app = APP.read_text(encoding="utf-8")
    onboarding = ONBOARDING.read_text(encoding="utf-8")
    assert "InviteOnboarding" in app
    assert "inviteRouteState" in app
    assert "client.auth.updateUser({ password })" in onboarding
    assert "await client.auth.signOut()" in onboarding
    assert "Set up your PBHS Mathematics account" in onboarding
    assert "signUp" not in app + onboarding


def test_documentation_records_free_plan_and_authorization_boundaries():
    text = DOC.read_text(encoding="utf-8")
    assert "Leaked Password Protection is unavailable" in text
    assert "department_profiles" in text
    assert "user_metadata" in text
    assert "No real PBHS staff" in text
    assert "temporary password" not in text.lower()
