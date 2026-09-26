# Phase 7.2 — Correction Evidence Reinterpretation

## Contract

Correction input is evidence, not a patch.

1. teacher submits typed/photo/upload evidence;
2. evidence is reinterpreted into a structured proposal;
3. proposal is shown back to the teacher;
4. only explicit confirmation permits the Phase 7.1 overlay to apply it;
5. deterministic validation runs again.

## Deterministic-first implementation

Typed evidence is interpreted directly. Photo/upload evidence is downloaded from the
private correction namespace and passed through the existing ingestion + normalisation/OCR
stack. No new OCR or document parser is introduced.

The first controlled proposal family is question-number repair:
- `unlabeled_mark_bearing_question` -> `promote_unlabeled_question`;
- `numbering_jump` / `suspicious_question_identifier` -> `rename_question_identifier`.

A proposal is created only when exactly one safe target question identifier can be
resolved. Ambiguous evidence remains `awaiting_reinterpretation`; it is never promoted by
confidence or guesswork.

The later [general teacher-language interpretation increment](PHASE7_6_TEACHER_LANGUAGE_INTERPRETATION.md)
extends this deterministic-first path to the full existing correction-operation
allowlist. This section records the original Phase 7.2 implementation and is retained
as history rather than rewritten to imply that broader interpretation existed then.

## Source provenance

A numbering overlay never rewrites the source file. Renamed questions retain
`source_question_id`, and canonicalisation segments the original source by that printed
identifier while exposing the corrected canonical number.

## Hosted worker

`.github/workflows/reinterpret-correction.yml` runs independently of the full memo worker.
It installs only the correction evidence dependencies and invokes
`engine.src.memo_engine.correction_reinterpretation`.

The live `submit-correction` Edge Function dispatches this workflow when a submitted
correction has no immediate deterministic proposal.

## Local qualification

- exact typed `11.2.1` -> structured rename proposal for `11.12.1`;
- two competing question identifiers -> unresolved, no proposal;
- synthetic PNG containing `11.2.1` -> Tesseract OCR -> same rename proposal;
- rename overlay preserves source identifier `11.12.1`;
- real RAW regression recovers the original working under canonical `11.2.1`;
- computed document total remains 138 because no mark descriptors are invented from
  the source text `(4) marks awarded`.
