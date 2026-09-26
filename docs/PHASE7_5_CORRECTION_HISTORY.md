# Phase 7.5 effective correction history

**ACCEPTED — Hosted RAW end-to-end acceptance completed successfully on 2026-09-26.**
See the [Phase 7.5 Accepted Baseline](../README.md#phase-75-accepted-baseline)
for the accepted run, implementation commit, and full result.

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

Hosted acceptance completed in Process Memo run `36212752841` on commit
`55792320fde6c2c86c62ca85d524a4b0849fe599`. The audit recorded 13 confirmed,
10 effective, 3 superseded, 10 effective applied, and zero application issues.
All supersession links were valid; the historical 3-mark override remained
confirmed but non-effective and unapplied in the current pass. The job reached
`complete / complete` with no active review exceptions, 11 questions totaling
150, canonical `render_ready`, and passing validation. Both hosted DOCX/PDF
outputs exist and passed preflight; the render-complete event records total 150.

The review page final audit uses `canonical.audit.correction_overlay` as its
correction source of truth. It requires a present and internally consistent audit,
zero application issues, every effective correction applied, every non-effective
entry linked to a valid `superseded_by` correction and left unapplied in the current
pass, and `applied_count == effective_count`. Missing audit data fails acceptance
explicitly, so output from an older worker cannot pass by falling back to database
`applied_at`. Historical database timestamps are logged only as diagnostics.

Parent discrepancy context was added after acceptance. The subsequent
[teacher-language interpretation increment](PHASE7_6_TEACHER_LANGUAGE_INTERPRETATION.md)
also preserves this accepted effective-history contract.
