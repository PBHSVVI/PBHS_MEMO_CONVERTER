from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from engine.src.memo_engine.renderer import (
    RENDER_PROFILE,
    RenderingError,
    _prepare_latex,
    _same_marking_scheme,
    render_outputs,
)


def _mark(mark_type: str = "answer", descriptor: str = "answer") -> dict:
    return {
        "mark_id": "m1",
        "type": mark_type,
        "count": 1,
        "descriptor": descriptor,
        "applies_to_block_ids": ["b1"],
        "source_shorthand": "1A",
        "consistent_accuracy": {"enabled": False, "dependency_item_ids": []},
        "acceptable_variants": [],
        "source_refs": [],
        "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
        "warnings": [],
    }


def _canonical(status: str = "render_ready") -> dict:
    return {
        "schema_version": "1.0",
        "document_id": "fixture",
        "status": status,
        "source": {"files": [], "assets": []},
        "document_metadata": {
            "exam_type": "PREPARATORY EXAMINATION",
            "year": 2026,
            "subject": "MATHEMATICS",
            "paper": "PAPER 1",
            "grade_label": "FORM 5",
            "language": "en-ZA",
            "exam_code": None,
            "expected_total_marks": 1,
            "duration_minutes": 60,
            "observed_page_count_text": None,
        },
        "render_profile": RENDER_PROFILE,
        "notes": [],
        "questions": [
            {
                "question_id": "q1",
                "number": "1",
                "heading": "QUESTION 1",
                "context_blocks": [],
                "items": [
                    {
                        "item_id": "q1_1",
                        "number": "1.1",
                        "context_blocks": [],
                        "children": [],
                        "alternatives": [
                            {
                                "alternative_id": "q1_1_primary",
                                "label": "PRIMARY",
                                "blocks": [
                                    {
                                        "block_id": "b1",
                                        "type": "math",
                                        "semantic_role": "answer",
                                        "math": {
                                            "source_text": "x²=1",
                                            "canonical_latex": "x^2=1",
                                            "presentation_mathml": None,
                                            "plain_text": "x²=1",
                                            "display_mode": "display",
                                        },
                                        "source_refs": [],
                                        "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
                                        "warnings": [],
                                    }
                                ],
                                "marking_points": [_mark()],
                                "marks_computed": 1,
                                "source_refs": [],
                            }
                        ],
                        "marks": {"observed": 1, "computed": 1, "status": "match"},
                        "source_refs": [],
                        "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
                        "warnings": [],
                    }
                ],
                "subtotal": {"observed": 1, "computed": 1, "status": "match"},
                "source_refs": [],
                "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
                "warnings": [],
            }
        ],
        "totals": {"observed": 1, "computed": 1, "expected": 1, "status": "match"},
        "exceptions": [],
        "corrections": [],
        "audit": {},
    }


class Phase6RendererTests(unittest.TestCase):
    def test_rejects_non_render_ready(self) -> None:
        with self.assertRaises(RenderingError) as cm:
            render_outputs(_canonical("blocked"), b"", tempfile.mkdtemp())
        self.assertEqual(cm.exception.code, "RENDER_INPUT_NOT_READY")

    def test_identical_alternative_marking_scheme_collapses(self) -> None:
        alts = [
            {"label": "PRIMARY", "marking_points": [_mark()]},
            {"label": "OR", "marking_points": [_mark()]},
        ]
        self.assertTrue(_same_marking_scheme(alts))
        alts[1]["marking_points"][0] = _mark("method", "method")
        self.assertFalse(_same_marking_scheme(alts))

    def test_half_open_interval_transport_is_balanced(self) -> None:
        value = _prepare_latex(r"x\in(-\infty;2]\cup(3;\infty)")
        self.assertIn(r"\left(", value)
        self.assertIn(r"\right]", value)

    @unittest.skipUnless(
        shutil.which("pandoc") and (shutil.which("libreoffice") or shutil.which("soffice")),
        "Pandoc and LibreOffice are required for renderer integration",
    )
    def test_tiny_render_ready_memo_reaches_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = render_outputs(_canonical(), b"", td)
            self.assertTrue(Path(result["docx_path"]).exists())
            self.assertTrue(Path(result["pdf_path"]).exists())
            self.assertGreaterEqual(result["page_count"], 3)
            self.assertTrue(result["docx_preflight"]["passed"])
            self.assertTrue(result["pdf_preflight"]["passed"])
            self.assertIn("✓", result["pdf_preflight"]["required_glyphs"])


if __name__ == "__main__":
    unittest.main()
