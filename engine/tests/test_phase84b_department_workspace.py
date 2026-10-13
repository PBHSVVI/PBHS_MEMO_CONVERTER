from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "web" / "src" / "components" / "Dashboard.jsx"
MODEL = ROOT / "web" / "src" / "lib" / "paperWorkspace.js"
SERVICE = ROOT / "web" / "src" / "lib" / "memoService.js"
STYLES = ROOT / "web" / "src" / "styles.css"
MIGRATIONS = ROOT / "supabase" / "migrations"


def test_workspace_hierarchy_and_single_active_form_contract():
    source = DASHBOARD.read_text(encoding="utf-8") + MODEL.read_text(encoding="utf-8")
    for label in (
        "Department",
        "Work state",
        "Quick filter",
        "All papers",
        "My papers",
    ):
        assert label in source
    assert 'role="tablist"' in source
    assert 'aria-selected={form === number}' in source
    assert "Recent conversions" not in source
    assert "Needs my attention" not in source


def test_department_library_uses_summary_and_preserves_owner_jobs():
    source = SERVICE.read_text(encoding="utf-8")
    assert '.from("jobs")' in source
    assert '.from("paper_library_summary")' in source
    assert "department_profiles" not in source
    assert "storage.objects" not in source


def test_responsive_contract_keeps_form_tabs_scrollable():
    css = STYLES.read_text(encoding="utf-8")
    assert ".form-tabs" in css
    assert "overflow-x: auto" in css
    assert "@media (max-width: 768px)" in css
    assert "@media (max-width: 440px)" in css
    assert ".paper-card" in css


def test_expected_migration_history_is_explicit():
    migration_names = {path.name for path in MIGRATIONS.glob("*.sql")}
    assert migration_names == {
        "0001_core.sql",
        "0002_storage_and_tenant_hardening.sql",
        "0003_foreign_key_indexes.sql",
        "0004_phase7_correction_lifecycle.sql",
        "0005_phase7_correction_overlay_reconciliation.sql",
        "0006_phase81b_teacher_metadata.sql",
        "0007_phase83a_department_library.sql",
        "0008_support_incidents.sql",
    }
