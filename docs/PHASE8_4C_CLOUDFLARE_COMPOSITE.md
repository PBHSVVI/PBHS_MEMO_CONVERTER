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

## Phase 8.4C.1 completion attempt — 2026-10-23

The fixture-aware gate repair was committed as
`2e790208ddc14242b773200a3ae33a1c21ed3374`. Local qualification passed with 41
focused Phase 8.4C tests and 686 full-engine tests, with 4 skips and 28
subtests. Hosted Phase 8 qualification run `39907253411` passed on the same
commit.

The previous Stage-V transcript was not reusable: the earlier workflow retained
only a sanitized digest and quality summary, not the actual provider transcript
in a legitimate private checkpoint. Activation run `39907373744` therefore made
one newly authorized Stage-V call. Gemma returned a PASS transcript containing
all required equation values, labels A and B, and the overlap relationship, with
no unsupported numeric values. Its transcript digest was
`550000f41816f728c8d45d76147f4de961f228206176b1efaa0e79dddc03a4f4`.

The run then made its one authorized Stage-S call to
`@cf/meta/llama-3.3-70b-instruct-fp8-fast`. The provider returned structured JSON,
but deterministic validation rejected it with `AI_PROVIDER_GROUNDING_MISSING`.
The sanitized report intentionally does not contain the private wrapper, so the
missing grounding path cannot be identified without a separately designed,
privacy-safe diagnostic change. Production-schema validation, final
`ProviderResult`, cache replay, and cached failover did not run.

The attempt used exactly one Stage-V and one Stage-S inference call, made no
retries or agreement requests, and recorded zero billable spend under the
free-only gate. Activation variables remain unset. Cloudflare composite remains
inactive, and Stage 1B remains blocked pending an offline grounding diagnostic
and a separately authorized live qualification.

## Phase 8.4C.2 grounding coverage repair

The exact missing path from the Phase 8.4C.1 provider response cannot be
established because private Stage-S content was intentionally not logged. The
offline audit nevertheless established the defect class: the v1 validator used
a hand-maintained subset of payload fields, the wrapper schema could not require
dynamic leaf coverage, and failure diagnostics reported only the general error
code. This allowed structurally incomplete model grounding to reach the
validator without identifying the uncovered leaf.

The v2 contract uses one recursive JSON Pointer enumerator over the populated
payload. Array indexes are explicit, RFC 6901 escaping is applied, null or empty
optional values and empty containers create no requirement, and every populated
leaf is content-bearing unless it matches an explicit exemption. Coverage is an
exact set comparison; parent-prefix coverage is forbidden.

The current production exemptions are:

- payload schema version and page, which come from the request contract;
- evidence kind, confidence, and fixed source enum, which remain bounded and
  independently checked by production validation and role-integrity gates;
- mark-change level, confidence, and the fixed confirmation flag, which remain
  bounded and independently validated.

All other populated leaves require grounding. This includes visual-presence
claims, question references, transcriptions, normalized mathematics, visible
mark values, warning text, and every coordinate of a non-null model-supplied
bounding box. Unknown future fields therefore fail closed as content-bearing
rather than becoming implicitly exempt.

Supplied mappings are checked against exact leaf paths. Unknown paths, container
paths, and metadata paths are rejected. Identical duplicates are deterministically
deduplicated; conflicting duplicates fail. Every remaining content path requires
an exact Stage-V quotation after bounded whitespace normalization. Numeric tokens
and mathematical labels must occur in the path's quote. Exact transcription
matching ensures a spatial relationship quote contains its reported entities and
relationship instead of mentioning only one label.

Failure diagnostics contain only JSON Pointer paths, counts, classifications,
and mismatch categories. They never include transcript text, quotations, payload
values, image bytes, or credentials. Grounding failures are classified as
`content_request`, so they fail closed without opening a provider-capacity
circuit or creating teacher infrastructure-review noise.

The Stage-S prompt now derives its field policy from the same exemption constants
used by validation and explicitly requires one indexed mapping per populated
content leaf. The wrapper schema requires
`cloudflare-grounded-wrapper-v2`, strengthens path syntax and duplicate guidance,
and the Stage-S prompt version is `cloudflare-grounded-structurer-v2`. Old Stage-S
cache entries are invalidated while unchanged Stage-V cache identity remains
reusable.

Grounding proves provenance only. Existing question-versus-solution integrity,
source-backed spatial preservation, and deterministic mathematical-consistency
checks remain subsequent independent gates. The deterministic layer detects
missing grounding and never manufactures a quotation from payload content.

Offline qualification completed with 22 grounding-coverage tests, 41 remaining
Phase 8.4C composite/activation tests, 16 Phase 8.4A tests, 24 Phase 8.4B.4 tests,
and Slice 1–4 results of 15, 7 with 1 local skip, 23, and 29 tests. The complete
engine suite passed with 708 tests, 4 skips, and 28 subtests. No Cloudflare,
Groq, or Mistral inference was called, and all activation variables remained
unset. Hosted qualification is required before another bounded live proof can
be recommended.

Hosted Phase 8 quality qualification run `39913251755` passed the existing
qualification matrix on repair commit
`fbc89e6ad2b199a280c9a7bb29e6d253fa6987bd`. The workflow was then updated to
include the new grounding-coverage suite explicitly; the final hosted result is
recorded below.

Final hosted qualification run `39913423259` passed on commit
`61f32bf7455b6ff2701f8f4797fba802c1624866`, including all 63 Phase 8.4C
grounding/composite/activation tests. Phase 8.4C.2 is offline-qualified. Another
bounded synthetic Stage-V/Stage-S live proof is technically justified, but it
requires separate authorization. Cloudflare composite remains inactive and
Stage 1B remains blocked until that proof passes.

## Phase 8.4C.3 final live re-proof — 2026-10-23

Before inference, the activation harness was extended to report safe grounding
path counts, validation outcomes, and the final result digest on success. Local
qualification passed with 63 focused Phase 8.4C tests and 708 full-engine tests,
with 4 skips and 28 subtests. Hosted qualification run `39914772607` passed on
commit `32ada018d3951427a2dc4e782bfa06f1a598292e`.

No legitimate reusable Stage-V checkpoint existed. The retained earlier
artifacts contained sanitized digests and summaries only, not an actual provider
transcript. Activation run `39914911963` therefore made one Stage-V call to
`@cf/google/gemma-4-26b-a4b-it`. The observer transcript passed: all required
equation values, labels A and B, and the overlap relationship were recovered,
the visible two-circle cardinality was accepted, and no unsupported number was
reported. The transcript digest was
`601e6c78ccf74ce36f50a5a031904760cbc377bd4a3c48fbe00c9cbc6b3a3e94`.

The run then made its one authorized Stage-S call to
`@cf/meta/llama-3.3-70b-instruct-fp8-fast`. Cloudflare rejected the request with
HTTP 400 and provider code `8007` before a grounded wrapper was returned. No
grounding coverage, production-schema, final ProviderResult, cache replay, or
cached failover result therefore exists for this run. The run used exactly two
inference calls, made no retries, recorded zero billable spend, and left all
activation variables unset.

Offline comparison isolated a JSON Mode transport-schema compatibility
regression. The same model had returned structured JSON for the v1 wrapper, while
the v2 provider-facing schema added `pattern` and `uniqueItems`. Those keywords
are no longer sent to the model. Exact JSON Pointer syntax, complete leaf
coverage, duplicate/conflict handling, quote occurrence, numeric and label
support, relationship support, and question-to-answer protection remain fully
enforced by the deterministic v2 validator. This changes only the schema used to
request JSON from Cloudflare; it does not weaken the accepted grounding contract.

The transport repair passed 63 focused Phase 8.4C tests and the complete engine
suite with 708 tests, 4 skips, and 28 subtests. Hosted qualification run
`39915321445` then passed on repair commit
`ee4f61b0007c84a222da397d27e4096320249375`. This qualification made no provider
inference and is not authorization for another live attempt. Cloudflare composite
remains inactive, Mistral remains excluded, and Stage 1B remains blocked pending
a separately authorized bounded re-proof.
