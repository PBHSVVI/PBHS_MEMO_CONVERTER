from __future__ import annotations

import json
import unittest

from engine.src.memo_engine.metadata import (
    MAX_TEACHER_METADATA_BYTES,
    MetadataValidationError,
    normalize_teacher_metadata,
    resolve_document_metadata,
)


EMPTY = {"schema_version": "1.0", "values": {}, "confirmed_absent": []}


class Phase81BMetadataTests(unittest.TestCase):
    def test_source_wins_teacher_conflict(self) -> None:
        result = resolve_document_metadata(
            "MATHEMATICS PAPER 2 FORM 5 TIME: 3 HOURS 2026",
            {"schema_version": "1.0", "values": {"paper": "PAPER 1"}, "confirmed_absent": []},
            teacher_metadata_revision=2,
        )
        self.assertEqual(result["effective"]["paper"], "PAPER 2")
        audit = result["audit"]["fields"]["paper"]
        self.assertEqual(audit["selected_provenance"], "source")
        self.assertTrue(audit["teacher_conflict_ignored"])
        self.assertEqual(audit["teacher_metadata_revision"], 2)

    def test_teacher_fills_missing_form_and_duration(self) -> None:
        result = resolve_document_metadata(
            "PREPARATORY EXAMINATION MATHEMATICS PAPER 2 2026",
            {
                "schema_version": "1.0",
                "values": {"grade_label": "form 5", "duration_minutes": 180},
                "confirmed_absent": [],
            },
            teacher_metadata_revision=1,
        )
        self.assertEqual(result["effective"]["grade_label"], "FORM 5")
        self.assertEqual(result["effective"]["duration_minutes"], 180)
        self.assertEqual(result["audit"]["fields"]["grade_label"]["selected_provenance"], "teacher")
        self.assertEqual(result["audit"]["fields"]["duration_minutes"]["selected_provenance"], "teacher")
        self.assertEqual(result["missing_fields"], [])

    def test_absent_values_remain_null_and_request_one_review(self) -> None:
        result = resolve_document_metadata("MATHEMATICS PAPER 2 2026", EMPTY)
        self.assertIsNone(result["effective"]["grade_label"])
        self.assertIsNone(result["effective"]["duration_minutes"])
        self.assertEqual(result["missing_fields"], ["grade_label", "duration_minutes"])

    def test_confirmed_absent_stays_null_without_repeated_review(self) -> None:
        result = resolve_document_metadata(
            "MATHEMATICS PAPER 2 2026",
            {"schema_version": "1.0", "values": {}, "confirmed_absent": ["grade_label", "duration_minutes"]},
        )
        self.assertEqual(result["missing_fields"], [])
        self.assertIsNone(result["effective"]["duration_minutes"])
        self.assertTrue(result["audit"]["fields"]["duration_minutes"]["confirmed_absent"])

    def test_source_contradiction_fails_closed(self) -> None:
        result = resolve_document_metadata(
            "PAPER 1 PAPER 2 FORM 5 FORM 6 TIME: 2 HOURS TIME: 3 HOURS",
            EMPTY,
        )
        self.assertIsNone(result["effective"]["paper"])
        self.assertIn("paper", result["source_conflicts"])
        self.assertIn("grade_label", result["source_conflicts"])
        self.assertIn("duration_minutes", result["source_conflicts"])

    def test_same_source_value_keeps_source_provenance(self) -> None:
        result = resolve_document_metadata(
            "PAPER 2",
            {"schema_version": "1.0", "values": {"paper": "paper2"}, "confirmed_absent": []},
        )
        self.assertEqual(result["audit"]["fields"]["paper"]["selected_provenance"], "source")
        self.assertFalse(result["audit"]["fields"]["paper"]["teacher_conflict_ignored"])

    def test_retry_resolution_is_deterministic(self) -> None:
        payload = {"schema_version": "1.0", "values": {"grade_label": "FORM 5", "duration_minutes": 180}, "confirmed_absent": []}
        first = resolve_document_metadata("PAPER 2 2026", payload, teacher_metadata_revision=4)
        second = resolve_document_metadata("PAPER 2 2026", payload, teacher_metadata_revision=4)
        self.assertEqual(first, second)

    def test_unknown_and_total_fields_are_rejected(self) -> None:
        for field in ("unknown", "expected_total_marks", "total_marks"):
            with self.subTest(field=field), self.assertRaises(MetadataValidationError):
                normalize_teacher_metadata({"values": {field: 150}})

    def test_malformed_payload_is_rejected(self) -> None:
        for payload in ([], {"values": []}, {"confirmed_absent": "grade_label"}):
            with self.subTest(payload=payload), self.assertRaises(MetadataValidationError):
                normalize_teacher_metadata(payload)

    def test_oversized_payload_is_rejected(self) -> None:
        payload = {"values": {"subject": "X" * (MAX_TEACHER_METADATA_BYTES + 1)}}
        self.assertGreater(len(json.dumps(payload).encode()), MAX_TEACHER_METADATA_BYTES)
        with self.assertRaises(MetadataValidationError):
            normalize_teacher_metadata(payload)

    def test_computed_total_is_not_part_of_metadata(self) -> None:
        result = normalize_teacher_metadata(EMPTY)
        self.assertNotIn("expected_total_marks", result["values"])
        self.assertNotIn("total_marks", result["values"])


if __name__ == "__main__":
    unittest.main()
