# General teacher-language interpretation

## Hosted accepted baseline

**ACCEPTED — Hosted teacher-language interpretation acceptance completed successfully.**

Accepted on **2026-09-29** using disposable job
`e0055801-f512-4573-8389-2c084eb43fe2`. The live fast-model case ran in
[Reinterpret Correction run 36292433279](https://github.com/PBHSVVI/PBHS_MEMO_CONVERTER/actions/runs/36292433279),
and the completed correction history converged in
[Process Memo run 36533348435](https://github.com/PBHSVVI/PBHS_MEMO_CONVERTER/actions/runs/36533348435)
at commit `6bc1101837f2f0de3edf16a5ba5743cc7c2a4b7b`. The final run passed
**113 tests on Python 3.13.15**.

The accepted evidence covers deterministic interpretation without a model call,
one live fast-model interpretation, strict proposal validation, teacher show-back,
explicit confirmation, fail-closed unresolved and provider/schema failures,
edit/resubmit and rejection, effective overlay application, revalidation, and final
rendering. The accepted Phase 7.5 RAW job
`a284e625-6a71-43bd-ac81-7679a29de421` remained unchanged; its final database event
and update timestamp remain **2026-09-26**.

## Baseline protection

Phase 7.5 remains the formally accepted hosted RAW baseline recorded in the
[project README](../README.md#phase-75-accepted-baseline). This increment extends
correction reinterpretation without changing effective correction history,
supersession, conditional scoring, canonical validation, deterministic rendering,
or the Phase 7.5 final audit.

The governing rule is:

**AI handles ambiguity. Structured operations and deterministic validation remain truth.**

Teacher language is evidence. It is never executable authority, and no interpreted
proposal applies until the teacher confirms it through the existing review flow.

## Interpretation ladder

The correction worker follows one bounded ladder:

1. **Tier 0 — deterministic.** Existing parsers run first. A proposal is dry-run
   through the authoritative correction overlay. When it passes, processing stops
   and no model is called.
2. **Tier 1 — fast interpretation.** Only unresolved evidence is sent to Groq
   `openai/gpt-oss-20b`. The model receives the active exception, teacher text,
   limited suggestions, a local source excerpt, the current question and relevant
   parent discrepancies. It must return the closed JSON contract below.
3. **Tier 2 — strong interpretation.** Groq `openai/gpt-oss-120b` is called at most
   once when the fast result explicitly remains ambiguous, produces inconsistent
   mark semantics, or yields a proposal rejected by the deterministic overlay.
   Provider failures, unsupported operations, wrong targets and ungrounded values
   remain unresolved instead of consuming a second call.

Typed evidence uses this path directly. Photo and upload evidence retains local
ingestion and Tesseract first, with the existing approved vision transcription only
when necessary. The language interpreter sees extracted text, not an arbitrary file.

## Bounded operation contract

The canonical allowlist is defined in `memo_engine.corrections` and shared with the
interpreter:

- `replace_mark_points`
- `set_item_total_override`
- `set_printed_marks`
- `rename_question_identifier`
- `promote_unlabeled_question`
- `insert_missing_major_question`
- `set_question_subtotal`
- `replace_item_content` (structured editor only; available for every active review)

Teacher-language operations are restricted to compatible exception categories.
`replace_item_content` is constructed by the validated structured editor rather
than by the AI response contract. There is no
generic patch, object path, database command, source mutation or multi-operation
transaction.

The AI response is a strict object with every field present and
`additionalProperties: false`:

```json
{
  "status": "resolved | ambiguous | unsupported",
  "operation": "allowlisted operation or null",
  "affected_id": "active identifier or null",
  "target_id": "grounded identifier or null",
  "printed_marks": 4,
  "subtotal": null,
  "expected_total": null,
  "mark_calculation_mode": null,
  "mark_points": [],
  "reason": "concise rationale",
  "evidence_basis": [],
  "ambiguities": []
}
```

Nullable operation fields remain null when they do not apply. Mark-point entries
are also closed objects containing `count`, `code` and `descriptor`; codes are
limited to `M`, `A`, `CA`, `F`, `S` and `R`. An unresolved response cannot carry an
operation or mark points.

## Deterministic safety gates

Provider schema enforcement is repeated locally. The interpreter then requires:

- the operation to match the active exception category;
- `affected_id` to equal the active exception target;
- question targets to occur in teacher evidence or an existing bounded suggestion;
- totals and subtotals to be explicit in the teacher wording;
- mark descriptors to be grounded in the teacher wording;
- computed mark total and calculation mode to agree with the proposed points; and
- the complete proposal to pass a dry run through `apply_confirmed_corrections` on
  a copy of the current structure.

The last gate reuses the same operation application and structural checks that are
authoritative after confirmation. AI does not declare its own proposal valid.
Conditional accuracy remains maximum-based: `2A for 3 correct; 1A for 2 correct`
is a two-mark alternative, not three additive marks.

The prompt forbids solving mathematics, inventing identifiers or marks, creating a
missing question from numbering alone, changing neighbours, forcing a 150-mark
total, using GOLD values, and silently combining independent corrections. Insufficient
evidence returns to teacher review.

## Confirmation and teacher show-back

Resolved proposals continue into the existing `awaiting_confirmation` state. The
review page presents a plain-language interpretation first. Replacement schemes show
each proposed mark point, for example `1M — factorising`, while the operation name
and JSON remain under technical details. The teacher can confirm, edit and resubmit,
or cancel. Nothing is applied at reinterpretation time.

When interpretation is unresolved, the normal message says that the evidence was
saved, nothing was applied, and asks for one specific identifier, total or marking
instruction. Raw provider errors stay in technical audit data.

## Provenance and cost controls

The reinterpretation artifact and job events record:

- deterministic, fast, strong and unresolved counts;
- interpretation method;
- provider, model and tier;
- supplied bounded context and resulting proposal;
- token usage and latency when returned by the provider;
- escalation reason;
- concise evidence, ambiguity and validation results; and
- the proposal later shown for teacher confirmation.

No hidden reasoning is stored. Provider failure leaves the correction pending and
records a recoverable error code. One fast call and, when justified, one strong call
are the maximum. The existing artifact and event model holds this provenance, so no
database migration is required.

## Qualification and limits

Regression tests use an injected provider seam; they never call live Groq. Coverage
includes deterministic preservation, conditional scoring, natural numbering, mark
totals, mark schemes, subtotals, unlabelled and missing questions, strict schema,
grounding, wrong targets, unsupported operations, overlay rejection, provider
failure, single strong escalation and unresolved strong results. Review-page tests
exercise the richer show-back model.

The interpreter deliberately handles one logical correction per active exception.
Independent compound changes remain ambiguous. AI-produced `alternative_max`
schemes that require richer branch structure than the existing mark-point operation
can express remain for teacher clarification; the accepted deterministic conditional
syntax continues to work.

## Hosted acceptance evidence

The following Supabase corrections and their private `reinterpretation.json`
artifacts provide the representative hosted evidence:

- `09e9e4d5-35d8-432e-aeb1-7156b55b99a6` used
  `deterministic_teacher_mark_total` / `set_printed_marks`;
  `0346851c-a1ab-4ba9-9ba6-e86d0bfc52cc` used
  `deterministic_teacher_mark_scheme` / `replace_mark_points`; and
  `c0d2ede7-eeb2-4fb4-96eb-beac4ef0ae5f` used
  `deterministic_teacher_subtotal` / `set_question_subtotal`. Each recorded a passed
  deterministic validation, one deterministic resolution, zero fast calls, zero
  strong calls and an empty provider-run list. Each reinterpretation event preceded
  confirmation, and each correction was later applied by the confirmed overlay.
- `b2a0faeb-c9e3-435b-802a-cda13f15a839` exercised the live fast path through Groq
  `openai/gpt-oss-20b`. It produced the closed
  `insert_missing_major_question` proposal for Question 10, passed the deterministic
  dry run, recorded exactly one fast call and zero strong calls, and stored 1,218
  prompt tokens, 210 output tokens, 1,428 total tokens and 448 ms latency. Its
  plain-language proposal was stored before the explicit confirmation event. The
  confirmed operation appears in the final effective overlay with `applied: true`.
- `fa46a1c4-fff5-42b6-bdc2-f78b540a1e9c`,
  `b6f0ebaf-e7e2-4e22-b4de-efa477f3a8c5`,
  `6020750c-1162-4f53-be0f-a6dcc0c41254` and
  `855f1da1-3091-4a5d-a0a2-66bdba0e5d40` remained unresolved and unapplied.
  Their artifacts retained provider or validation provenance, including
  `AI_PROVIDER_JSON_VALIDATE_FAILED`, `AI_AFFECTED_ID_MISMATCH` and
  `AI_TARGET_NOT_GROUNDED`. They were rejected and remained auditable; replacement
  corrections `09e9e4d5…`, `0346851c…`, `b2a0faeb…` and `c0d2ede7…` subsequently
  resolved the same review issues.

The final disposable job state was `complete / complete` with zero active exceptions
and zero correction application issues. Its correction overlay recorded **9
confirmed, 9 effective and 9 applied** corrections. Canonical output was
`render_ready`, validation passed, and the result contained **11 major questions and
150 marks**. DOCX and PDF preflights passed, both output files exist, and the
`phase6_render_complete` event records total 150.

| Acceptance requirement | Result | Evidence |
| --- | --- | --- |
| Deterministic zero-model resolution | PASS | `09e9e4d5…`, `0346851c…`, `c0d2ede7…`; empty provider runs |
| Live fast-model interpretation | PASS | `b2a0faeb…`; Groq `openai/gpt-oss-20b`; run `36292433279` |
| Strict structured proposal | PASS | Closed schema and allowlist; stored Question 10 proposal |
| Deterministic dry-run validation | PASS | Passed validation in deterministic and fast-path events |
| Teacher-facing show-back | PASS | Stored display text and confirmation-ready review state |
| No mutation before confirmation | PASS | Reinterpretation precedes confirmation; rejected rows have no `confirmed_at` or `applied_at` |
| Explicit confirmation | PASS | Confirmed events and timestamps for every effective interpreted correction |
| Correct overlay application | PASS | Final history has 9 effective and 9 applied, with zero issues |
| Revalidation | PASS | `phase7_revalidation_complete`: total 150, `render_ready`, validation passed |
| Unresolved ambiguity fail-closed | PASS | Representative rejected corrections retained no executable proposal or application |
| Edit/resubmit | PASS | Four rejected attempts were followed by successful replacements on the same exceptions |
| Cancel/reject | PASS | Rejected rows remain unapplied and auditable |
| Provenance/audit storage | PASS | Reinterpretation events and private artifacts retain method, validation, model, token and latency data |
| Accepted Phase 7.5 RAW job unchanged | PASS | Baseline job has no event or update after 2026-09-26 |
| Strong-model path qualification | PASS (qualified) | Mocked regression coverage and one-call implementation cap |

**Strong hosted escalation path not reproducibly exercised; locally qualified by mocked regression tests.**

The local suite covers one justified fast-to-strong escalation, deterministic-overlay
rejection followed by one strong call, an unresolved strong result, schema and
provider failures, and the one-call cap. The implementation performs one fast
attempt and at most one strong attempt; non-escalatable failures return unresolved.
