from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "docs" / "pbhs-design-tokens.css"
REVIEW = ROOT / "docs" / "phase7-5-review" / "index.html"
WEB_STYLES = ROOT / "web" / "src" / "styles.css"
SIGN_IN = ROOT / "web" / "src" / "components" / "SignIn.jsx"
ONBOARDING = ROOT / "web" / "src" / "components" / "InviteOnboarding.jsx"


def _colours() -> dict[str, str]:
    text = TOKENS.read_text(encoding="utf-8")
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", text))


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_teacher_and_review_apps_share_one_provisional_token_source() -> None:
    tokens = TOKENS.read_text(encoding="utf-8")
    web = WEB_STYLES.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    assert "Provisional accessible UI colours derived" in tokens
    assert '@import "../../docs/pbhs-design-tokens.css"' in web
    assert '<link rel="stylesheet" href="../pbhs-design-tokens.css">' in review
    assert "--pbhs-navy:" not in web
    assert "--pbhs-navy:" not in review


def test_identity_hierarchy_uses_the_canonical_crest_without_signup_copy() -> None:
    sign_in = SIGN_IN.read_text(encoding="utf-8")
    onboarding = ONBOARDING.read_text(encoding="utf-8")
    for label in ("Pretoria Boys High School", "Mathematics Department", "Memo Converter"):
        assert label in sign_in
    assert "Create my account" in onboarding
    assert "signUp" not in sign_in + onboarding
    assert (ROOT / "web" / "public" / "branding" / "pbhs-125-crest.png").is_file()


def test_core_text_and_action_colours_meet_wcag_aa() -> None:
    colours = _colours()
    white = colours["pbhs-surface"]
    for foreground in ("pbhs-navy", "pbhs-ink", "pbhs-muted", "pbhs-red", "pbhs-green", "pbhs-gold-text"):
        assert _contrast(colours[foreground], white) >= 4.5, foreground


def test_desktop_tablet_and_phone_layout_hooks_are_present() -> None:
    web = WEB_STYLES.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    assert "width: min(1180px" in web
    assert "@media (max-width: 768px)" in web
    assert "@media (max-width: 440px)" in web
    assert "@media(max-width:1024px)" in review
    assert "@media(max-width:900px)" in review
    assert "@media(max-width:600px)" in review
    assert ".proposal .buttonRow{position:sticky;bottom:0" in review
