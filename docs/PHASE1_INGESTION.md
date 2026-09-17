# Phase 1 — Deterministic Ingestion

Phase 1 introduces real source-file ingestion without AI.

## Accepted source classes

- PDF
- DOCX
- PNG
- JPEG

Maximum Phase 1 source size: 50 MB.

## Hosted worker sequence

1. Read the dispatched job.
2. Validate that `source_path` is inside `{user_id}/{job_id}/source/`.
3. Download the private object from Supabase Storage.
4. Compute SHA-256 and byte size.
5. Detect source type using file signatures/package structure, with extension fallback.
6. Extract digital text deterministically:
   - PDF: `pypdf`
   - DOCX: direct OOXML parsing
   - PNG/JPEG: no OCR yet; record that OCR/vision is required.
7. Write `{user_id}/{job_id}/internal/ingestion.json`.
8. Record source fingerprint and a metadata-only audit event.
9. Stop at `failed_retryable / PHASE1_DOWNSTREAM_NOT_YET_CONNECTED` until the next phase is connected.

## Privacy/logging rule

Extracted source text is written only to the private internal ingestion artifact.
It is not emitted to GitHub Actions logs or `job_events` payloads.
