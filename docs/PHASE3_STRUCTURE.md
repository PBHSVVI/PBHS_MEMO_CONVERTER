# Phase 3 — Deterministic Memo Structure + Exception Gates

Phase 3 adds question/mark structure extraction without external AI.

## Inputs

- `internal/normalized.json`
- original source bytes

## Outputs

- `internal/structure.json`
- zero or more rows in `public.exceptions`

## Deterministic extraction

- question identifiers and hierarchy candidates
- printed `(n)` allocations
- shorthand mark candidates
- question subtotals `[n]`
- arithmetic comparison between printed marks and deterministic shorthand counts

## Exception gates

The parser raises Amber/Red rather than silently correcting:

- suspicious numbering jumps
- duplicate identifiers
- likely missing identifiers
- multiple printed allocations
- printed-vs-counted mark mismatches
- unexpected subtotal sums
- structurally unusual identifiers such as `11.12.1`

Phase 3 intentionally does not auto-correct source numbering or infer ambiguous mark semantics.

## Expected benchmark behaviour

For RAW Paper 1, Phase 3 should enter:

- `needs_review`
- `stage = phase3_structured`
- `error_code = PHASE3_REVIEW_REQUIRED`

and persist the exceptions for teacher review.

No external AI call is made.
