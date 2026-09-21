# Phase 7.1 — Confirmed Correction Overlay and Revalidation

## Purpose

Apply a teacher-confirmed correction as an interpretation overlay while preserving the uploaded source as immutable evidence.

## Locked rules

- Pending/rejected corrections never alter structure, canonical data or output.
- Confirmed patches are applied only when the operation is explicitly supported and deterministically validated.
- Unsupported confirmed patches create a new blocking exception rather than being ignored or guessed.
- Previous unresolved analysis rows are retained as `superseded`; resolved correction-linked rows remain audit evidence.
- The worker revalidates after correction application and renders only when all review gates pass.

## First supported overlay

`unlabeled_mark_bearing_question` + confirmed numbering suggestion:

- resolve exactly one unlabelled source row;
- promote it to the confirmed question identifier;
- preserve source block provenance;
- retain printed allocation and deterministic mark points;
- remove only the corrected structural exception.

The controlled RAW benchmark uses this path to promote the unlabelled row to Question 2.2. Local regression verifies:

- Q2.2 = 4 marks;
- Question 2 changes from computed 22 to 26, matching the observed subtotal;
- document canonical computed total changes from 134 to 138;
- unrelated RAW defects remain blocking.

## Partial semantic cache

When a correction changes only part of the semantic candidate set, previously Green AI results are reused candidate-by-candidate only when ID, question, mark index, mark count, shorthand and descriptor all match exactly. New/changed candidates alone are sent to the provider. This prevents a local correction from consuming another full-document AI pass.

## Automatic redispatch

Future explicit confirmations transition the job through `correction_confirmed` to `dispatched`. The same job ID is reused. A dedicated `resume-correction` endpoint exists for previously confirmed but not-yet-applied corrections and controlled recovery.

## Typed/photo/upload safety

Typed text, photographs and uploads are evidence only at submission. They remain `awaiting_reinterpretation` until the interpretation worker produces a structured proposal that can be shown back for confirmation.
