from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "docs" / "pbhs-design-tokens.css"
STYLES = ROOT / "web" / "src" / "styles.css"
DASHBOARD = ROOT / "web" / "src" / "components" / "Dashboard.jsx"
WORKSPACE_MODEL = ROOT / "web" / "src" / "lib" / "paperWorkspace.js"


def test_authenticated_header_has_one_bounded_heritage_stripe():
    css = STYLES.read_text(encoding="utf-8")
    stripe = css.split(".topbar::after", 1)[1].split("}", 1)[0]
    assert "height: 12px" in stripe
    assert "var(--pbhs-red) 0 5px" in stripe
    assert "var(--pbhs-surface) 5px 7px" in stripe
    assert "var(--pbhs-green) 7px 12px" in stripe
    assert css.count(".topbar::after") == 1


def test_workspace_canvas_is_tinted_while_surfaces_remain_white():
    tokens = TOKENS.read_text(encoding="utf-8")
    assert "--pbhs-canvas: #eef1f0;" in tokens
    assert "--pbhs-surface: #ffffff;" in tokens


def test_sign_in_and_workspace_information_architecture_remain_present():
    css = STYLES.read_text(encoding="utf-8")
    workspace = DASHBOARD.read_text(encoding="utf-8") + WORKSPACE_MODEL.read_text(encoding="utf-8")
    assert ".auth-shell" in css
    assert "background: var(--pbhs-navy-deep)" in css
    for label in ("Mathematics", "FS Mathematics", "In progress", "Completed", "All papers", "My papers", "Upload memo"):
        assert label in workspace
