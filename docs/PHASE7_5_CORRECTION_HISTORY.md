# Phase 7.5 effective correction history

Confirmed corrections remain immutable audit evidence. Before replay, the engine
derives an effective history so obsolete marking decisions cannot regenerate
application exceptions on every revalidation.

## Supersession rules

Only confirmed corrections participate. They are ordered by confirmation instant,
then correction ID for deterministic ties. Legacy entries without valid timestamps
precede dated entries and retain their supplied order.

For the same exact affected question identifier:

- A supported `replace_mark_points` supersedes older `replace_mark_points` and
  `set_item_total_override` decisions.
- A supported `set_item_total_override` supersedes only older item-total overrides.
  It composes with an earlier scheme, against which its total is still validated.
- Printed-allocation selection, numbering, source evidence, subtotal operations,
  and operations on other targets remain independent.

The latest effective operation must still pass the existing deterministic checks.
An invalid replacement blocks review; the engine does not silently fall back to an
older decision. Unsupported operations remain visible as application failures.
Question aliases across renames are not inferred for supersession. Existing replay
ordering and target validation continue to govern numbering/marking composition.

In the reported 11.1.1 case, historical correction
`473f7290-4ce4-4d8c-a269-20705d92de7a` (3-mark item override) is superseded by the
later confirmed conditional scheme. The engine starts from the immutable source
allocation of 2, applies the 2A/1A thresholds as maximum 2, and never replays the
obsolete override. There is no special case for this UUID in the implementation.

## Audit output

`structure.correction_overlay` and `canonical.audit.correction_overlay` record
confirmed, effective, superseded, applied and issue counts, plus per-correction
history. Each history entry contains `effective`, `superseded_by`, the reason,
domain, and `applied` for the current pass. The correction application event also
includes this history.

`canonical.corrections` retains every confirmed proposal, display text and
confirmation timestamp. `historical_applied_at` preserves any prior application
timestamp; it does not imply application during the current pass. Supersession
does not delete rows, reject teacher confirmations, or overwrite teacher evidence.
No database migration or live repair is required.

## Validation and hosted acceptance

Run with Python 3.13:

```sh
python -m pytest -q engine/tests
```

Regression coverage includes the obsolete 3-mark decision, successive schemes,
independent numbering and other targets, unconfirmed input, invalid replacements,
total-only composition, canonical partial credit/audit, repeatability and ordering.

Hosted acceptance remains required. Revalidate the existing RAW job on the updated
worker and inspect the old correction's `superseded_by`, effective application
count, and zero application issues. Verify all effective corrections applied,
11 questions with subtotals 23, 26, 4, 14, 8, 13, 20, 13, 8, 5, 16, total 150,
no active review exceptions, canonical/validation readiness, DOCX/PDF outputs and
both preflights, and the teacher download flow.

The review page final audit uses `canonical.audit.correction_overlay` as its
correction source of truth. It requires a present and internally consistent audit,
zero application issues, every effective correction applied, every non-effective
entry linked to a valid `superseded_by` correction and left unapplied in the current
pass, and `applied_count == effective_count`. Missing audit data fails acceptance
explicitly, so output from an older worker cannot pass by falling back to database
`applied_at`. Historical database timestamps are logged only as diagnostics.

Parent discrepancy context in review and the broader teacher-language interpreter
remain separate follow-ups.
