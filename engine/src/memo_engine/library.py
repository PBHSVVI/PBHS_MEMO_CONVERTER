from __future__ import annotations

import re
from typing import Any


SUBJECT_SCOPES = {
    "MATHEMATICS": "mathematics",
    "FS MATHEMATICS": "fs_mathematics",
}


def subject_scope(subject: Any) -> str | None:
    """Return a library scope only for an explicit resolved subject label."""
    if not isinstance(subject, str):
        return None
    normalized = re.sub(r"\s+", " ", subject).strip().upper()
    return SUBJECT_SCOPES.get(normalized)


def workflow_bucket(status: Any) -> str:
    return "completed" if status == "complete" else "in_progress"


def paper_library_summary(
    job: dict[str, Any],
    canonical: dict[str, Any],
) -> dict[str, Any]:
    """Build the safe server-maintained library row from canonical truth."""
    metadata = canonical.get("document_metadata") or {}
    filing = job.get("filing_metadata") or {}
    has_filing = filing.get("schema_version") == "1.0"
    totals = canonical.get("totals") or {}
    resolved_subject = (
        "FS MATHEMATICS"
        if filing.get("subject_scope") == "fs_mathematics"
        else "MATHEMATICS"
        if filing.get("subject_scope") == "mathematics"
        else metadata.get("subject")
    )
    filing_paper = filing.get("paper") or {}
    filing_number = filing.get("assessment_number") or {}
    duration = filing.get("duration") or {}
    assessment_labels = {
        "class_test": "CLASS TEST",
        "standardised_test": "STANDARDISED TEST",
        "investigation": "INVESTIGATION",
        "examination": "EXAMINATION",
    }
    return {
        "job_id": job["id"],
        "owner_user_id": job["user_id"],
        "subject_scope": subject_scope(resolved_subject),
        "subject_display": resolved_subject,
        "assessment_type": assessment_labels.get(filing.get("assessment_type")) if has_filing else metadata.get("exam_type"),
        "assessment_number": filing_number.get("value") if has_filing else None,
        "year": filing.get("year") if has_filing else metadata.get("year"),
        "paper": (
            f"PAPER {filing_paper['value']}" if filing_paper.get("value") else None
        ) if has_filing else metadata.get("paper"),
        "grade_label": f"FORM {filing['form']}" if has_filing and filing.get("form") else metadata.get("grade_label"),
        "duration_value": duration.get("value") if has_filing else None,
        "duration_unit": duration.get("unit") if has_filing else None,
        "duration_minutes": duration.get("duration_minutes") if has_filing else metadata.get("duration_minutes"),
        "expected_total_marks": metadata.get("expected_total_marks"),
        "computed_total_marks": totals.get("computed"),
        "term": f"TERM {filing['term']}" if has_filing and filing.get("term") else None,
        "display_name": job.get("display_name"),
        "source_filename": job.get("source_filename"),
        "workflow_bucket": workflow_bucket(job.get("status")),
        "status_source": job.get("status"),
        "stage_source": job.get("stage"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "completed_at": job.get("completed_at"),
    }
