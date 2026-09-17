# Phase 4 — Semantic Interpretation + Quota-Aware AI Routing

Phase 4 is the first external-AI stage.

## Contract

AI interprets. Code renders.

AI is permitted to classify ambiguous marking semantics only after deterministic
ingestion, normalisation and structure gates have run.

AI may NOT:

- change question numbering
- change printed marks or subtotals
- repair structural exceptions
- invent missing mathematics
- override source-integrity or mark-arithmetic gates

## Default provider

Primary provider: Groq.

Fast model:
- `openai/gpt-oss-20b`

Escalation model:
- `openai/gpt-oss-120b`

Only candidates that are not safely resolved by deterministic rules are sent to
the provider. Fast-model results that are non-green, below 0.90 confidence or
incompatible with shorthand constraints are escalated.

## Privacy

Default runtime mode:
- `APPROVED_EXTERNAL_ONLY`
- approved provider: `groq`

Only compact mark-semantic packets are sent externally. Packets contain question
number, a short local question-context excerpt, the mark descriptor/shorthand and
neighboring mark descriptors.

Packets do NOT contain:
- user ID
- teacher email
- filename
- Supabase object path
- whole document content

Set `MEMO_PRIVACY_MODE=LOCAL_ONLY` to disable external interpretation entirely.

## Hard semantic constraints

- M -> method
- CA -> consistent_accuracy
- R -> reason
- A -> accuracy or answer only
- F -> formula or factorisation only
- S -> statement, substitution or simplification only

A model result that violates these constraints cannot become Green.

## Durable outputs

Private Storage:
- `internal/semantic.json`

Audit events:
- `phase4_interpreter_run`
- `phase4_semantic_complete`

The interpreter-run event records provider/model, candidate count, token usage,
latency and privacy mode. Prompt/source content is never written to job events.

## Expected milestone stop

If any structural or semantic exception remains:
- `status = needs_review`
- `stage = phase4_semantic_interpreted`
- `error_code = PHASE4_REVIEW_REQUIRED`

If no exception remains:
- `status = failed_retryable`
- `stage = phase4_semantic_interpreted`
- `error_code = PHASE4_MATH_CANONICALIZATION_NOT_YET_CONNECTED`

Phase 5 will canonicalise mathematics and assemble the controlled interpretation
schema.

## Free-tier pacing

Phase 4 batches ambiguous marks and deliberately spaces provider calls. The default is 16 candidates per request with a 15-second minimum interval between batches, reducing the chance of exhausting token-per-minute quotas. The values are runtime-configurable.
