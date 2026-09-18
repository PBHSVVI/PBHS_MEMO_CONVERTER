# Phase 5.1 — Groq structured-output recovery

## Live failure addressed

The first hosted Phase 5 RAW/GOLD acceptance run proved the RAW path end-to-end,
including the Phase 4 semantic cache and Phase 5 canonicalisation. The fresh GOLD
semantic pass then received:

- HTTP 400
- type: `invalid_request_error`
- code: `json_validate_failed`

The deterministic/canonical Phase 5 layers were not implicated.

## Recovery policy

`json_validate_failed` is now treated as a retryable provider structured-output
failure, alongside `tool_use_failed`.

For a multi-candidate batch:
1. retry the affected batch one candidate at a time;
2. retain locally validated successful candidates;
3. unresolved candidates continue into the existing strong-model escalation;
4. if a provider still cannot safely classify a candidate, create controlled
   semantic review rather than terminating the entire memo.

Hard provider configuration/authentication/permission failures remain fatal.

No numbering, arithmetic, source-integrity, semantic shorthand, privacy or
canonical-validation gate is weakened.
