# Phase 8 visual evidence fusion

Status: **implemented; hosted hybrid/write-on acceptance pending**.

The existing digital extraction pipeline remains authoritative for printed
question structure, identifiers, allocations and totals. Visual evidence is a
parallel layer. It is attached to existing question anchors and is never
concatenated into the whole-page digital text stream.

## Routing

1. PyPDF preserves digital text.
2. PyMuPDF screens every PDF page for ink annotations, raster overlays,
   non-text vector drawings, coloured content, image pages and explicit
   write-on wording.
3. Tesseract remains the local fallback for pages that fail the existing text
   quality gate.
4. Only flagged page/question regions are rendered for visual interpretation.
5. Only the configured and approved Groq provider may receive rendered image
   data. The model is configured independently with
   `MEMO_GROQ_VISION_MODEL`.
6. Low-confidence, unreadable or unassociated evidence becomes teacher review.

The visual model transcribes visible evidence. Its prompt forbids solving an
unanswered question, inventing marks, reproducing printed questions as memo
evidence, or silently repairing unclear handwriting.

## Private artifacts

Artifacts remain in the authenticated job namespace:

- `internal/visual/pages/page-NNNN.png`
- `internal/visual/regions/page-NNNN-qX_X.png`
- `internal/visual/evidence.json`

The evidence record contains page/region provenance, model identity,
confidence, raw transcription and normalized mathematics where safe. Image
bytes and provider request bodies are never logged. Identical rendered regions
are sent once per run, and a source-hash-matched evidence record is reused on
deterministic retry.

## Fusion and review

High-confidence answer evidence becomes a solution segment on its existing
question. The printed prompt remains separately preserved as source context.
Ticks and crosses remain supporting evidence and do not invent marking points.
Handwritten mark changes remain candidates and require teacher confirmation;
they never overwrite printed allocations automatically.

The review application downloads a focused crop through authenticated private
storage. Teachers can accept a readable transcription through the existing
auditable content-correction path, edit/replace it, or submit new evidence.

Phase 8 must not be declared accepted until a new private hybrid/write-on memo
has completed controlled hosted acceptance. Existing live jobs are not reused
or destroyed for this validation.
