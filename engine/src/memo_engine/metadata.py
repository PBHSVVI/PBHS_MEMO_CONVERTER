from __future__ import annotations

import json
import re
from typing import Any

SUPPORTED_FIELDS = ("subject", "paper", "exam_type", "year", "grade_label", "duration_minutes")
REQUIRED_REVIEW_FIELDS = ("grade_label", "duration_minutes")
MAX_TEACHER_METADATA_BYTES = 4096
_OUTER_KEYS = {"schema_version", "values", "confirmed_absent"}
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_PAPER_RE = re.compile(r"(?i)\bPAPER\s*([12])\b")
_GRADE_RE = re.compile(r"(?i)\b(FORM|GRADE)\s*([0-9]{1,2})\b")
_DURATION_RE = re.compile(r"(?i)\bTIME\s*[:=-]?\s*(\d+(?:[.,]\d+)?)\s*HOURS?\b")


class MetadataValidationError(ValueError):
    pass


def _compact_text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise MetadataValidationError(f"{field} must be text")
    result = re.sub(r"\s+", " ", value).strip()
    if not result or len(result) > maximum:
        raise MetadataValidationError(f"{field} must contain between 1 and {maximum} characters")
    return result


def normalize_field(field: str, value: Any) -> str | int:
    if field == "subject":
        return _compact_text(value, field=field, maximum=80).upper()
    if field == "exam_type":
        return _compact_text(value, field=field, maximum=80).upper()
    if field == "paper":
        match = re.fullmatch(r"(?i)PAPER\s*([12])", _compact_text(value, field=field, maximum=20))
        if not match:
            raise MetadataValidationError("paper must be PAPER 1 or PAPER 2")
        return f"PAPER {match.group(1)}"
    if field == "grade_label":
        match = re.fullmatch(r"(?i)(FORM|GRADE)\s*([0-9]{1,2})", _compact_text(value, field=field, maximum=20))
        if not match:
            raise MetadataValidationError("grade_label must be a value such as FORM 5 or GRADE 12")
        number = int(match.group(2))
        if not 1 <= number <= 13:
            raise MetadataValidationError("grade_label number is out of range")
        return f"{match.group(1).upper()} {number}"
    if field == "year":
        if isinstance(value, bool) or not isinstance(value, int) or not 2000 <= value <= 2100:
            raise MetadataValidationError("year must be a four-digit assessment year")
        return value
    if field == "duration_minutes":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 720:
            raise MetadataValidationError("duration_minutes must be an integer from 1 to 720")
        return value
    raise MetadataValidationError(f"unknown teacher metadata field: {field}")


def normalize_teacher_metadata(payload: Any) -> dict[str, Any]:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise MetadataValidationError("teacher_metadata must be an object")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise MetadataValidationError("teacher_metadata must be valid JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_TEACHER_METADATA_BYTES:
        raise MetadataValidationError("teacher_metadata is too large")
    unknown_outer = set(payload) - _OUTER_KEYS
    if unknown_outer:
        raise MetadataValidationError("unknown teacher_metadata keys: " + ", ".join(sorted(unknown_outer)))
    if payload.get("schema_version", "1.0") != "1.0":
        raise MetadataValidationError("unsupported teacher_metadata schema_version")
    raw_values = payload.get("values", {})
    if not isinstance(raw_values, dict):
        raise MetadataValidationError("teacher_metadata.values must be an object")
    unknown_values = set(raw_values) - set(SUPPORTED_FIELDS)
    if unknown_values:
        raise MetadataValidationError("unknown teacher metadata fields: " + ", ".join(sorted(unknown_values)))
    values = {field: normalize_field(field, value) for field, value in raw_values.items()}
    raw_absent = payload.get("confirmed_absent", [])
    if not isinstance(raw_absent, list) or any(not isinstance(field, str) for field in raw_absent):
        raise MetadataValidationError("confirmed_absent must be a list of field names")
    unknown_absent = set(raw_absent) - set(SUPPORTED_FIELDS)
    if unknown_absent:
        raise MetadataValidationError("unknown confirmed_absent fields: " + ", ".join(sorted(unknown_absent)))
    confirmed_absent = sorted(set(raw_absent), key=SUPPORTED_FIELDS.index)
    overlap = set(values) & set(confirmed_absent)
    if overlap:
        raise MetadataValidationError("fields cannot have both a value and confirmed absence: " + ", ".join(sorted(overlap)))
    return {"schema_version": "1.0", "values": values, "confirmed_absent": confirmed_absent}


def _single_candidate(candidates: set[str | int]) -> tuple[str | int | None, list[str | int]]:
    ordered = sorted(candidates, key=str)
    if len(ordered) == 1:
        return ordered[0], []
    return (None, ordered) if ordered else (None, [])


def extract_source_metadata(text: str) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    source_text = text or ""
    upper = source_text.upper()
    candidate_sets: dict[str, set[str | int]] = {
        "subject": {"MATHEMATICS"} if re.search(r"\bMATHEMATICS\b", upper) else set(),
        "paper": {f"PAPER {value}" for value in _PAPER_RE.findall(source_text)},
        "exam_type": {"PREPARATORY EXAMINATION"} if re.search(r"\bPREPARATORY(?:\s+EXAMINATION)?\b", upper) else set(),
        "year": {int(value) for value in _YEAR_RE.findall(source_text)},
        "grade_label": {f"{kind.upper()} {int(number)}" for kind, number in _GRADE_RE.findall(source_text)},
        "duration_minutes": {int(round(float(value.replace(",", ".")) * 60)) for value in _DURATION_RE.findall(source_text)},
    }
    values: dict[str, Any] = {}
    conflicts: dict[str, list[Any]] = {}
    for field in SUPPORTED_FIELDS:
        value, conflict = _single_candidate(candidate_sets[field])
        values[field] = value
        if conflict:
            conflicts[field] = conflict
    return values, conflicts


def resolve_document_metadata(
    source_text: str,
    teacher_payload: Any,
    *,
    teacher_metadata_revision: int = 0,
    require_missing_review: bool = True,
) -> dict[str, Any]:
    teacher = normalize_teacher_metadata(teacher_payload)
    source, source_conflicts = extract_source_metadata(source_text)
    teacher_values = teacher["values"]
    confirmed_absent = set(teacher["confirmed_absent"])
    effective: dict[str, Any] = {}
    fields: dict[str, dict[str, Any]] = {}
    for field in SUPPORTED_FIELDS:
        source_value = source[field]
        teacher_present = field in teacher_values
        teacher_value = teacher_values.get(field)
        if field in source_conflicts:
            effective_value, provenance = None, "absent"
        elif source_value is not None:
            effective_value, provenance = source_value, "source"
        elif teacher_present:
            effective_value, provenance = teacher_value, "teacher"
        else:
            effective_value, provenance = None, "absent"
        effective[field] = effective_value
        fields[field] = {
            "field": field,
            "selected_provenance": provenance,
            "source_present": source_value is not None or field in source_conflicts,
            "teacher_present": teacher_present,
            "teacher_conflict_ignored": source_value is not None and teacher_present and teacher_value != source_value,
            "confirmed_absent": field in confirmed_absent,
            "teacher_metadata_revision": int(teacher_metadata_revision or 0),
        }
    missing_fields = [
        field for field in REQUIRED_REVIEW_FIELDS
        if require_missing_review
        and effective[field] is None
        and field not in confirmed_absent
        and field not in source_conflicts
    ]
    return {
        "effective": effective,
        "audit": {
            "schema_version": "1.0",
            "teacher_metadata_revision": int(teacher_metadata_revision or 0),
            "fields": fields,
            "source_conflicts": sorted(source_conflicts),
        },
        "missing_fields": missing_fields,
        "source_conflicts": source_conflicts,
        "teacher_metadata": teacher,
    }
