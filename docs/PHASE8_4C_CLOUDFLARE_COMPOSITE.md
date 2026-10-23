# Phase 8.4C Cloudflare composite structured vision

Status: **implemented; live qualification incomplete**

## Decision

The direct Cloudflare structured-vision route is retired. Gemma 4, Qwen 3.8,
and Llama 3.2 Vision remain classified as vision-only models and do not expose
`structured_visual` individually. Production capability decisions use only the
current `developers.cloudflare.com` JSON Mode documentation. Preview-domain
documentation is not an activation authority.

The fallback is a two-stage composite:

1. Stage V sends a question-owned crop to a free-only Cloudflare vision model
   and requests a factual evidence transcript without JSON.
2. Stage S sends only that transcript to an account-visible, active, free-only
   model listed by the current production JSON Mode documentation.
3. Deterministic code validates every content-bearing claim against an exact
   transcript quotation before the normal production visual-evidence validator
   accepts the payload.

The preferred Stage-V model is `@cf/google/gemma-4-26b-a4b-it`. The preferred
Stage-S candidate is `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, subject to live
account visibility. Deprecated models, paid-only models, and preview-only
capability claims are excluded.

## Grounding contract

Stage S returns an internal wrapper with `payload` and `grounding`. Grounding
entries use JSON Pointer paths and exact quotations from the Stage-V transcript.
The validator requires whitespace-normalized quotation presence, rejects new
numeric tokens and mathematical labels, rejects missing grounding, and prevents
question-only text from becoming answer evidence. It therefore cannot silently
repair visibly incorrect arithmetic.

Content fields requiring grounding include evidence question references,
transcriptions, normalized mathematics, mark-change question references and
numeric values, and warning text. Deterministic metadata is exempt: schema and
page identifiers, provider/model identity, confidence, closed role/kind enums,
source/provenance digests, bounding boxes, and internal status fields.

## Cache, provenance, and failure isolation

Stage V cache identity contains source digest, crop digest, prompt version, and
vision model. Stage S identity contains transcript digest, production schema
version, prompt version, and structurer model. The private checkpoint retains a
successful transcript if Stage S fails, so a retry does not repeat image
inference. Final provenance records both model identities and both digests.

Failures identify either `cloudflare:visual_evidence` or
`cloudflare:json_structurer`. Stage-V failure prevents Stage S. Stage-S failure
retains the private Stage-V checkpoint and results in infrastructure deferral,
without creating a teacher-review flood.

No transcript is written to workflow logs or sanitized activation reports. It
exists only in the converter's private checkpoint record. AI Gateway logging,
R2, KV, Durable Objects, Vectorize, batch storage, paid spillover, and Mistral
school-private routing remain disabled.

## Activation gate

Activation requires both live stages, deterministic grounding, production
schema validation, content-quality checks, full cache replay, cached failover,
privacy gates, and zero-cost gates to pass. Repository variables are not set
until that complete proof succeeds. Stage 1B remains blocked until the live
qualification result is recorded here.

## Hosted qualification record — 2026-10-23

Hosted Phase 8 quality qualification passed on run `39905804990` at commit
`c3e0baf86ecffd5ce24628c8f29919656775e67c`.

The bounded activation run `39905909163` discovered 73 account-visible models.
It selected `@cf/google/gemma-4-26b-a4b-it` for Stage V and
`@cf/meta/llama-3.3-70b-instruct-fp8-fast` for Stage S. Both were visible, and
the structurer passed the active, production-documented, free-only selection
gate. No agreement request was made.

Stage V made one live synthetic inference call. It recovered every required
equation value (`10`, `250`, `1/25`, `0.04`, and `4%`), labels A and B, and the
overlap relation. The activation harness nevertheless classified the result as
partial because its expected-number set omitted `2`, although the fixture
visibly contains two circles. Stage S was therefore correctly not called. The
run used one total inference call, incurred no billable spend, and did not set
activation variables.

The synthetic gate now reads expected equation fragments, labels, relationship
terms, numeric tokens, and spatial cardinalities from the deterministic fixture
manifest. The visible two-circle cardinality is accepted only for a fixture
that declares it; a separate regression proves it remains unsupported for a
fixture that does not. The live success gate remains unmet because the one-call
budget for that activation run was not retried and Stage S, grounding,
production-schema, cache, and failover live proofs did not execute. A separately
authorized bounded activation run is required before Stage 1B.
