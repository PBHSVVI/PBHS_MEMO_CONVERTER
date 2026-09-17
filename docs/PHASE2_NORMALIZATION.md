# Phase 2 — Deterministic Document Normalisation + OCR Triage

Phase 2 remains a zero-external-AI stage.

## Principles

- Preserve digital source structure whenever it exists.
- OCR only when deterministic evidence says OCR is needed.
- Never overwrite usable digital text with OCR guesses.
- Keep memo text in private Storage artifacts, not GitHub logs or `job_events`.
- Local OCR runs only on the ephemeral GitHub-hosted runner.

## DOCX

The worker preserves:

- top-level paragraph/table order
- paragraph text
- paragraph style hints
- Word numbering identifiers/levels
- Office Math text and raw OMML fragments
- drawing counts
- embedded media metadata and hashes

No OCR is used for ordinary DOCX digital structure.

## PDF

Each page records:

- dimensions
- digital text
- image count
- OCR gate decision + reasons
- local OCR text if required
- effective text source

Digital text remains authoritative where usable. OCR is additional evidence rather than a silent replacement.

## Images

PNG/JPEG sources receive local Tesseract OCR.

## Outputs

Private Storage:

- `internal/ingestion.json`
- `internal/normalized.json`

Expected Phase 2 terminal state:

- `failed_retryable`
- `stage = phase2_normalized`
- `error_code = PHASE2_STRUCTURE_NOT_YET_CONNECTED`

This is an intentional milestone stop. Phase 3 will infer question hierarchy, memo items, mark allocations and exceptions.
