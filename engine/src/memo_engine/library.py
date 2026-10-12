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
    totals = canonical.get("totals") or {}
    resolved_subject = metadata.get("subject")
    return {
        "job_id": job["id"],
        "owner_user_id": job["user_id"],
        "subject_scope": subject_scope(resolved_subject),
        "subject_display": resolved_subject,
        "assessment_type": metadata.get("exam_type"),
        "year": metadata.get("year"),
        "paper": metadata.get("paper"),
        "grade_label": metadata.get("grade_label"),
        "duration_minutes": metadata.get("duration_minutes"),
        "expected_total_marks": metadata.get("expected_total_marks"),
        "computed_total_marks": totals.get("computed"),
        "term": None,
        "source_filename": job.get("source_filename"),
        "workflow_bucket": workflow_bucket(job.get("status")),
        "status_source": job.get("status"),
        "stage_source": job.get("stage"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "completed_at": job.get("completed_at"),
    }
