from __future__ import annotations

import unittest

from engine.src.memo_engine.canonical import (
    CanonicalizationError,
    _exception_record,
    omml_to_latex,
    plain_math_to_latex,
    validate_canonical,
    validate_latex_subset,
)
from engine.src.memo_engine.cli import _cached_semantic_matches

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def omml(inner: str) -> str:
    return f'<m:oMath xmlns:m="{M}">{inner}</m:oMath>'


class Phase5MathTests(unittest.TestCase):
    def test_fraction(self) -> None:
        value = omml(
            '<m:f><m:num><m:r><m:t>1</m:t></m:r></m:num>'
            '<m:den><m:r><m:t>2</m:t></m:r></m:den></m:f>'
        )
        self.assertEqual(omml_to_latex(value), r"\frac{1}{2}")

    def test_superscript(self) -> None:
        value = omml(
            '<m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e>'
            '<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>'
        )
        self.assertEqual(omml_to_latex(value), "{x}^{2}")

    def test_radical(self) -> None:
        value = omml(
            '<m:rad><m:radPr/><m:deg/><m:e><m:r><m:t>x</m:t></m:r></m:e></m:rad>'
        )
        self.assertEqual(omml_to_latex(value), r"\sqrt{x}")

    def test_source_braces_do_not_break_generated_latex(self) -> None:
        self.assertEqual(plain_math_to_latex("x²=4"), "x^{2}=4")

    def test_unsupported_command_fails_closed(self) -> None:
        with self.assertRaises(CanonicalizationError):
            validate_latex_subset(r"\unknown{x}")


class Phase5CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.structure = {
            "questions": [
                {
                    "question_id": "1.1",
                    "mark_points": [
                        {"count": 1, "code": "M", "descriptor": "method", "notation": "shorthand"},
                        {"count": 1, "code": "A", "descriptor": "answer", "notation": "shorthand"},
                    ],
                    "source_preview": "x=1",
                }
            ]
        }

    def test_exact_semantic_cache_matches(self) -> None:
        cached = {
            "phase": "phase4_semantics",
            "deterministic_results": [
                {
                    "candidate_id": "1_1__m1", "question_id": "1.1", "mark_index": 0,
                    "count": 1, "source_shorthand": "M", "descriptor": "method",
                },
                {
                    "candidate_id": "1_1__m2", "question_id": "1.1", "mark_index": 1,
                    "count": 1, "source_shorthand": "A", "descriptor": "answer",
                },
            ],
            "ai_results": [],
        }
        self.assertTrue(_cached_semantic_matches(self.structure, cached))

    def test_changed_candidate_rejects_cache(self) -> None:
        cached = {
            "phase": "phase4_semantics",
            "deterministic_results": [
                {
                    "candidate_id": "1_1__m1", "question_id": "1.1", "mark_index": 0,
                    "count": 1, "source_shorthand": "M", "descriptor": "different",
                }
            ],
            "ai_results": [],
        }
        self.assertFalse(_cached_semantic_matches(self.structure, cached))


class Phase5ValidationTests(unittest.TestCase):
    def test_amber_exception_has_all_free_correction_routes(self) -> None:
        record = _exception_record({
            "level": "amber",
            "category": "test",
            "affected_id": "1.1",
            "message": "Check this.",
            "suggestions": [{"candidate": "x"}],
        })
        self.assertEqual(
            record["allowed_user_actions"],
            ["select_suggestion", "type_edit", "take_photo", "upload_file"],
        )

    def test_empty_invalid_memo_fails(self) -> None:
        result = validate_canonical({})
        self.assertFalse(result["passed"])
        self.assertIn("schema_shape_invalid", result["error_codes"])


if __name__ == "__main__":
    unittest.main()
