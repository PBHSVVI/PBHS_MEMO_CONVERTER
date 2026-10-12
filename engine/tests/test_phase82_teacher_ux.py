from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REVIEW_PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def _html() -> str:
    return REVIEW_PAGE.read_text(encoding="utf-8")


def test_compact_review_information_order_and_navigation_hooks() -> None:
    html = _html()
    for label in (
        "1 · What's wrong / why the system is asking",
        "2 · Source evidence",
        "3 · Suggested interpretation / discrepancy",
        "4 · Editing tool",
        "5 · Save &amp; next",
    ):
        assert label in html
    assert 'id="issueJump"' in html
    assert 'aria-label="Jump to unresolved issue"' in html
    assert 'id="questionJump"' in html
    assert 'aria-label="Jump to question"' in html
    assert "Review ${position} / ${count}" in html
    assert "$('#issueJump').onchange" in html
    assert "$('#questionJump').onchange" in html


def test_tool_switcher_and_mark_allocation_use_teacher_language() -> None:
    html = _html()
    markup = html[: html.index('<script type="module">')]
    for label in ("Suggested fix", "Marks", "Content", "Numbering", "Evidence / Photo"):
        assert label in html
    assert "MARK ALLOCATION" in markup
    assert "Mark allocation · grouped" in markup
    assert "Mark allocation · single item" in markup
    assert "configureCorrectionTools" in html
    assert "markToolCategories" in html
    for operation in (
        "replace_mark_points",
        "replace_item_content",
        "resolve_question_allocation_pairing",
    ):
        assert operation not in markup


def test_save_next_and_responsive_sticky_hooks_remain_available() -> None:
    html = _html()
    assert 'id="confirm" class="primary">Save &amp; next</button>' in html
    assert ".reviewAction{position:sticky" in html
    assert ".proposal .buttonRow{position:sticky;bottom:0" in html
    assert "@media(max-width:1024px)" in html
    assert "@media(max-width:900px)" in html
    assert "@media(max-width:600px)" in html


def test_processing_copy_is_plain_language_without_fake_eta() -> None:
    html = _html()
    panel = re.search(r'<section id="processingPanel".*?</section>', html, re.S)
    assert panel
    copy = panel.group(0)
    assert "Elapsed:" in copy
    assert "You can safely leave this page and return later" in copy
    assert "Estimated remaining" not in copy
    for label in (
        "Reading your memo",
        "Checking question structure",
        "Interpreting the marking guideline",
        "Preparing your document",
        "Creating Word and PDF files",
    ):
        assert label in html


def test_review_page_has_no_duplicate_dom_ids() -> None:
    parser = _IdCollector()
    parser.feed(_html())
    duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    assert duplicates == []
