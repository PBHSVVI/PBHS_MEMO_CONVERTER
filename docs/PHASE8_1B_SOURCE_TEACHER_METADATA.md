# Phase 8.1B — Source and Teacher Document Metadata

Status: local implementation candidate. Hosted acceptance and production deployment are pending.

## Purpose

Phase 8.1B lets a teacher supply missing document-level cover details without treating those details as source evidence. It does not change question marks, correction replay, media ownership, geometry validation, or the accepted Phase 8.1A baseline.

## Precedence and supported fields

For each supported field, the deterministic order is:

1. valid explicit source metadata;
2. confirmed teacher fallback;
3. null.

Supported teacher fields are `subject`, `paper`, `exam_type`, `year`, `grade_label`, and `duration_minutes`. `expected_total_marks`, `language`, `exam_code`, and `observed_page_count_text` are not teacher-editable in this phase.

The computed memo total remains the sum of canonical question marks. Source-observed total remains source evidence. Teacher metadata cannot change either value or suppress arithmetic validation.

## Storage contract

`jobs.teacher_metadata` is a bounded JSONB object:

```json
{
  "schema_version": "1.0",
  "values": {
    "grade_label": "FORM 5",
    "duration_minutes": 180
  },
  "confirmed_absent": []
}
```

Unknown keys, nested values, total-mark fields, malformed values, and payloads over 4 KiB are rejected. `teacher_metadata_revision` increments for every accepted submission and `teacher_metadata_updated_at` records its time. The accepted normalized payload is also recorded in `job_events`.

The browser has no general update permission for this metadata. The authenticated `dispatch-memo` function validates ownership and payloads, stores the new revision, claims the job, and dispatches the worker.

## Resolution and audit

Effective scalar values remain in `canonical.document_metadata`. Per-field evidence is recorded in `canonical.audit.metadata_resolution.fields`:

- `selected_provenance`: `source`, `teacher`, or `absent`;
- `source_present`;
- `teacher_present`;
- `teacher_conflict_ignored`;
- `confirmed_absent`;
- `teacher_metadata_revision`.

A teacher value matching the source still has source provenance. A conflicting teacher value remains in the job/event audit but is ignored. Multiple contradictory source candidates fail closed into review.

No account data, filename assumption, CAPS expectation, render profile, teacher profile, or reference/gold memo is metadata evidence.

## Teacher flow

The upload screen contains a collapsed **Document details (optional)** section. Teachers can pre-supply metadata but do not have to open it.

After source processing, only missing `grade_label` and `duration_minutes` automatically trigger the single `missing_document_metadata` review condition. The Teacher App displays one **Document details need attention** card. Source-derived values are read-only and marked **From source**. Other non-source fields remain optional.

**Leave blank** records a field in `confirmed_absent`. Its effective value stays null and the worker does not reopen the same missing-field review on retry.

Completed jobs are immutable. Their effective metadata is read-only. Changing it requires a future revised-conversion workflow; this phase displays: “Create a revised conversion to change document details.”

## Retry and failure behavior

Normal retry sends no new metadata and reuses the stored payload and revision. Source extraction and precedence run again deterministically.

If GitHub workflow dispatch fails after accepting metadata, the job returns to its former state while retaining the accepted metadata revision. A completed job, unrelated review state, or non-owned job cannot be mutated through the metadata route.

## Rendering

The renderer consumes only effective canonical metadata. It no longer inserts `PAPER 1`, `PREPARATORY EXAMINATION`, `2026`, or a literal subject when those values are absent. Missing cover lines are omitted. Computed marks still render.

Duration formatting is deterministic:

- 60 → `1 HOUR`
- 90 → `1½ HOURS`
- 120 → `2 HOURS`
- 180 → `3 HOURS`

## Paper 2 fixture

The RAW Paper 2 source contains no Form/Grade and no duration. Without teacher metadata both fields remain null and one metadata review requests `grade_label` and `duration_minutes`.

With teacher values `FORM 5` and `180`, both effective values have teacher provenance. Source-explicit paper, year, assessment type, and subject continue to have source provenance.
