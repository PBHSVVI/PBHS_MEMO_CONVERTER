from __future__ import annotations

import copy
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document

from engine.src.memo_engine.cli import fail_processing_job
from engine.src.memo_engine.renderer import (
    M_NS,
    RENDER_PROFILE,
    W_NS,
    RenderingError,
    _all_math_variants,
    _append_omml,
    _extract_pandoc_math_bank,
    _math_bank_markers,
    _math_display_parts,
    _pandoc_math_bank,
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


def _text_paragraph(parent: ET.Element, text: str) -> None:
    paragraph = ET.SubElement(parent, f"{{{W_NS}}}p")
    run = ET.SubElement(paragraph, f"{{{W_NS}}}r")
    node = ET.SubElement(run, f"{{{W_NS}}}t")
    node.text = text


def _math_paragraph(parent: ET.Element, label: str) -> None:
    paragraph = ET.SubElement(parent, f"{{{W_NS}}}p")
    container = ET.SubElement(paragraph, f"{{{M_NS}}}oMathPara")
    equation = ET.SubElement(container, f"{{{M_NS}}}oMath")
    run = ET.SubElement(equation, f"{{{M_NS}}}r")
    node = ET.SubElement(run, f"{{{M_NS}}}t")
    node.text = label


def _pandoc_xml_fixture(
    latex_values: list[str],
    group_sizes: list[int],
    *,
    equation_outside_group: bool = False,
) -> ET.Element:
    root = ET.Element(f"{{{W_NS}}}document")
    body = ET.SubElement(root, f"{{{W_NS}}}body")
    if equation_outside_group:
        _math_paragraph(body, "outside")
    for index, (latex, group_size) in enumerate(zip(latex_values, group_sizes)):
        start, end = _math_bank_markers(index, latex)
        _text_paragraph(body, start)
        for equation_index in range(group_size):
            _math_paragraph(body, f"{index}:{equation_index}")
        _text_paragraph(body, end)
    return root


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

    def test_math_bank_maps_one_expression_to_one_omml_result(self) -> None:
        latex_values = ["x^2=1"]
        bank = _extract_pandoc_math_bank(
            _pandoc_xml_fixture(latex_values, [1]),
            latex_values,
        )
        self.assertEqual(len(bank["x^2=1"]), 1)

    def test_math_bank_retains_exact_mapping_for_unique_expressions(self) -> None:
        latex_values = ["x=1", "y=2", "z=3"]
        bank = _extract_pandoc_math_bank(
            _pandoc_xml_fixture(latex_values, [1, 1, 1]),
            latex_values,
        )
        labels = [
            "".join(node.itertext())
            for latex in latex_values
            for node in bank[latex]
        ]
        self.assertEqual(labels, ["0:0", "1:0", "2:0"])

    def test_multiple_omath_nodes_do_not_shift_later_mappings(self) -> None:
        latex_values = ["x=1$$ $$y=2", "z=3"]
        bank = _extract_pandoc_math_bank(
            _pandoc_xml_fixture(latex_values, [2, 1]),
            latex_values,
        )
        self.assertEqual(
            ["".join(node.itertext()) for node in bank[latex_values[0]]],
            ["0:0", "0:1"],
        )
        self.assertEqual(
            ["".join(node.itertext()) for node in bank[latex_values[1]]],
            ["1:0"],
        )

    def test_repeated_expression_reuses_one_math_bank_entry(self) -> None:
        canonical = _canonical()
        block = canonical["questions"][0]["items"][0]["alternatives"][0]["blocks"][0]
        canonical["questions"][0]["items"][0]["alternatives"][0]["blocks"].append(
            copy.deepcopy(block)
        )
        self.assertEqual(_all_math_variants(canonical), ["x^2=1"])

    def test_mixed_prose_and_math_display_parts_remain_split(self) -> None:
        block = {
            "math": {
                "source_text": "n=3 years 2 months",
                "canonical_latex": r"n=3\text{ years }2\text{ months}",
            }
        }
        self.assertEqual(
            _math_display_parts(block),
            [("math", "n=3"), ("text", " years 2 months")],
        )

    def test_explanatory_parenthetical_remains_wrappable_prose(self) -> None:
        block = {
            "math": {
                "source_text": "x=2 (correct answer)",
                "canonical_latex": r"x=2(correct answer)",
            }
        }
        self.assertEqual(
            _math_display_parts(block),
            [("math", "x=2"), ("text", " (correct answer)")],
        )

    def test_q7_2_trigonometric_parentheses_remain_native_math(self) -> None:
        cases = [
            (
                "=3k4(sin120cosθ-sinθcos120)",
                r"=\frac{3k}{4(sin120cos\theta{}-sin\theta{}cos120)}",
                r"\frac{3k}{4(sin120cos\theta{}-sin\theta{}cos120)}",
            ),
            (
                "=3k4(sin60cosθ+sinθcos60)",
                r"=\frac{3k}{4(sin60cos\theta{}+sin\theta{}cos60)}",
                r"\frac{3k}{4(sin60cos\theta{}+sin\theta{}cos60)}",
            ),
            (
                "=3k4(32cosθ+sinθ12)",
                r"=\frac{3k}{4(\frac{\sqrt{3}}{2}cos\theta{}+sin\theta{}\frac{1}{2})}",
                r"\frac{3k}{4(\frac{\sqrt{3}}{2}cos\theta{}+sin\theta{}\frac{1}{2})}",
            ),
            (
                "=3k4×12(3cosθ+sinθ)",
                r"=\frac{3k}{4\times{}\frac{1}{2}(\sqrt{3}cos\theta{}+sin\theta{})}",
                r"\frac{3k}{4\times{}\frac{1}{2}(\sqrt{3}cos\theta{}+sin\theta{})}",
            ),
        ]
        for source, latex, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(
                    _math_display_parts(
                        {"math": {"source_text": source, "canonical_latex": latex}}
                    ),
                    [("text", "= "), ("math", expected)],
                )

    def test_leading_equals_remains_plain_text_before_native_math(self) -> None:
        block = {"math": {"source_text": "=x+1", "canonical_latex": "=x+1"}}
        self.assertEqual(_math_display_parts(block), [("text", "= "), ("math", "x+1")])

    def test_trailing_equals_remains_plain_text_after_native_math(self) -> None:
        block = {"math": {"source_text": "x+1=", "canonical_latex": "x+1="}}
        self.assertEqual(_math_display_parts(block), [("math", "x+1"), ("text", " =")])

    def test_multiple_omath_nodes_are_appended_as_native_math(self) -> None:
        latex = "x=1$$ $$y=2"
        bank = _extract_pandoc_math_bank(
            _pandoc_xml_fixture([latex], [2]),
            [latex],
        )
        document = Document()
        paragraph = document.add_paragraph()
        _append_omml(paragraph, latex, bank)
        self.assertEqual(len(paragraph._p.findall(f"{{{M_NS}}}oMath")), 2)

    def test_unmapped_omml_fails_closed_with_safe_diagnostics(self) -> None:
        latex_values = ["x=1"]
        with self.assertRaises(RenderingError) as cm:
            _extract_pandoc_math_bank(
                _pandoc_xml_fixture(
                    latex_values,
                    [1],
                    equation_outside_group=True,
                ),
                latex_values,
            )
        self.assertEqual(cm.exception.code, "RENDER_MATH_MAPPING_FAILED")
        self.assertEqual(cm.exception.details["expected_expression_count"], 1)
        self.assertEqual(cm.exception.details["omath_count"], 2)
        self.assertNotIn("x=1", str(cm.exception.details))

    def test_zero_omml_group_fails_closed(self) -> None:
        latex_values = [r"\frac{3k}{4"]
        with self.assertRaises(RenderingError) as cm:
            _extract_pandoc_math_bank(
                _pandoc_xml_fixture(latex_values, [0]),
                latex_values,
            )
        self.assertEqual(cm.exception.code, "RENDER_MATH_MAPPING_FAILED")
        self.assertEqual(cm.exception.details["expected_expression_count"], 1)
        self.assertEqual(cm.exception.details["omml_container_count"], 1)
        self.assertEqual(cm.exception.details["omath_count"], 0)
        self.assertEqual(cm.exception.details["failing_expression_index"], 0)
        self.assertEqual(
            cm.exception.details["failing_expression_digest"],
            hashlib.sha256(latex_values[0].encode("utf-8")).hexdigest()[:16],
        )

    def test_rendering_diagnostics_are_recorded_without_changing_public_message(self) -> None:
        class FakeDatabase:
            def __init__(self) -> None:
                self.event = None

            def patch_job(self, job_id, expected_status, values):
                return {"id": job_id, **values}

            def add_event(self, job, event_type, stage, payload):
                self.event = (event_type, stage, payload)

        db = FakeDatabase()
        diagnostics = {
            "expected_expression_count": 2,
            "omml_container_count": 1,
            "failing_expression_index": 1,
            "failing_expression_digest": "0123456789abcdef",
        }
        fail_processing_job(
            db,
            {"id": "job"},
            code="PHASE6_RENDER_MATH_MAPPING_FAILED",
            message="Native equation conversion failed.",
            stage="rendering_failed",
            diagnostics=diagnostics,
        )
        self.assertEqual(
            db.event,
            (
                "worker_failed",
                "rendering_failed",
                {
                    "error_code": "PHASE6_RENDER_MATH_MAPPING_FAILED",
                    "diagnostics": diagnostics,
                },
            ),
        )

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required for OMML integration")
    def test_pandoc_multiple_omath_expression_keeps_following_mapping(self) -> None:
        canonical = _canonical()
        blocks = canonical["questions"][0]["items"][0]["alternatives"][0]["blocks"]
        blocks[0]["math"]["source_text"] = "x=1 and y=2"
        blocks[0]["math"]["canonical_latex"] = "x=1$$ $$y=2"
        second = copy.deepcopy(blocks[0])
        second["block_id"] = "b2"
        second["math"]["source_text"] = "z=3"
        second["math"]["canonical_latex"] = "z=3"
        blocks.append(second)
        bank = _pandoc_math_bank(canonical)
        self.assertEqual(len(bank["x=1$$ $$y=2"]), 2)
        self.assertEqual(len(bank["z=3"]), 1)

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc is required for OMML integration")
    def test_pandoc_q7_2_expressions_all_emit_native_omml(self) -> None:
        canonical = _canonical()
        blocks = canonical["questions"][0]["items"][0]["alternatives"][0]["blocks"]
        cases = [
            (
                "=3k4(sin120cosθ-sinθcos120)",
                r"=\frac{3k}{4(sin120cos\theta{}-sin\theta{}cos120)}",
            ),
            (
                "=3k4(sin60cosθ+sinθcos60)",
                r"=\frac{3k}{4(sin60cos\theta{}+sin\theta{}cos60)}",
            ),
            (
                "=3k4(32cosθ+sinθ12)",
                r"=\frac{3k}{4(\frac{\sqrt{3}}{2}cos\theta{}+sin\theta{}\frac{1}{2})}",
            ),
            (
                "=3k4×12(3cosθ+sinθ)",
                r"=\frac{3k}{4\times{}\frac{1}{2}(\sqrt{3}cos\theta{}+sin\theta{})}",
            ),
        ]
        blocks.clear()
        for index, (source, latex) in enumerate(cases, start=1):
            blocks.append(
                {
                    "block_id": f"b{index}",
                    "type": "math",
                    "semantic_role": "working",
                    "math": {
                        "source_text": source,
                        "canonical_latex": latex,
                        "presentation_mathml": None,
                        "plain_text": source,
                        "display_mode": "display",
                    },
                    "source_refs": [],
                    "confidence": {"score": 1.0, "band": "green", "rationale": "fixture"},
                    "warnings": [],
                }
            )
        values = _all_math_variants(canonical)
        bank = _pandoc_math_bank(canonical)
        self.assertEqual(len(values), 4)
        self.assertEqual(list(bank), values)
        self.assertTrue(all(len(bank[value]) == 1 for value in values))

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
