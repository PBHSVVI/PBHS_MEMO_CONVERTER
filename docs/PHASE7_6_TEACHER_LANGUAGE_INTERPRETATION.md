# General teacher-language interpretation

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

Each operation is also restricted to compatible exception categories. There is no
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

## Local qualification and limits

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
syntax continues to work. This implementation has local qualification only until a
separate hosted provider acceptance is run.

## Recommended hosted acceptance

Use a disposable review case rather than the accepted RAW job. Verify one example
at each rung: deterministic text with zero model calls, fast-model natural marking
language, justified fast-to-strong escalation, malformed/provider-failure recovery,
and unresolved ambiguity. For each case inspect the stored artifact and event,
plain-language show-back, edit/cancel path, explicit confirmation, effective overlay,
revalidation and final rendering. Confirm the configured model names, one-call caps,
token/latency fields, private evidence handling and absence of mutation before
confirmation.
