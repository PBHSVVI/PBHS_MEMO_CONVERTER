# Phase 4.3 — Exact semantic candidate schema

## Failure addressed

The provider successfully accepted Phase 4 requests, but a batch could return a
valid structured array containing fewer results than candidates or duplicate a
candidate ID. The previous JSON Schema constrained each item's shape but did not
constrain the batch cardinality/identity strongly enough.

## Fix

Each batch now creates a dynamic strict JSON Schema whose `results` object has:

- one property for every exact `candidate_id`
- every candidate property listed in `required`
- `additionalProperties: false`

The provider therefore cannot satisfy the schema while omitting a candidate,
duplicating one candidate in place of another, or returning an unexpected ID.

The adapter converts the keyed result back into the existing internal list shape,
so the downstream semantic validator and quota-routing architecture do not change.

No source text, privacy boundary, mark arithmetic, numbering rule, or model choice
is changed by this hotfix.
