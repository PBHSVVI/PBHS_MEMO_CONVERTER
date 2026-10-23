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

## Phase 8.4C.4 conservative transport and durable synthetic checkpoint

The full internal `cloudflare-grounded-wrapper-v2` schema is now distinct from
the provider-facing Cloudflare JSON Mode schema. At the start of this increment,
the recursively observed provider schema contained these JSON Schema keywords:
`additionalProperties`, `description`, `enum`, `items`, `maxItems`, `maximum`,
`minItems`, `minLength`, `minimum`, `properties`, `required`, and `type`. Its
compact serialized size for the deterministic activation fixture was 2,318
bytes.

`compile_cloudflare_transport_schema` now recursively retains only `type`,
`properties`, `required`, and `items`. Descriptions and all semantic, range,
length, vocabulary, uniqueness, and closed-object constraints remain in the
full internal schema or deterministic validation rather than being delegated to
Cloudflare. The Stage-S prompt states the allowed evidence kinds, source,
mark-change levels, confirmation flag, confidence range, bounding-box form,
closed-field rule, exact leaf-path requirement, and exact-quote rule.

After generation, the full internal wrapper is validated before grounding.
Malformed JSON Pointer syntax, duplicates and conflicting duplicates, invalid
closed vocabulary values, unsupported fields, incorrect types, omitted required
fields, missing or unknown grounding, unsupported numbers, labels or
relationships, and question-to-answer promotion all remain fail-closed.

The activation workflow now separates Stage V into its own successful job. A
passing transcript is written only when `privacy_classification` is exactly
`synthetic_test`, read back with its digest verified, stored as a bounded
14-day private workflow artifact, and cached by a digest of the complete fixture
identity. Cross-run reuse still validates fixture ID, source digest, crop digest,
Stage-V prompt version, Stage-V model, transcript presence, and transcript digest.
A mismatch fails rather than silently reusing or reconstructing content. The
Stage-S job downloads that exact same-run artifact, so it cannot erase the
successful synthetic Stage-V evidence if Stage S fails.

Live activation run `39917440395` used commit
`46e8384ba7d6364dc25080dfc27d5bea02815a9e`. Discovery again found 73 visible
models and selected the accepted Gemma/Llama pair. No compatible historical
synthetic cache existed, so Stage V made one call. The transcript passed every
content gate, was read back with digest
`b0779e3015ffedd734170e5ab56c6c137486fffe473f95394bd0e984bc104387`,
and was persisted both as the exact-identity Actions cache and as the bounded
private synthetic artifact before Stage S began.

Stage S made one call using the persisted transcript and the four-key transport
schema. Cloudflare accepted the request and returned JSON; HTTP 400/code 8007
did not recur. The full internal validator then rejected the wrapper at
`/wrapper/grounding_schema_version` with failure category
`internal_schema_enum`. No private enum value was logged. Grounding coverage,
production-schema validation, ProviderResult creation, replay, failover, and
activation therefore remained blocked.

This is a prompt-contract omission rather than a transport or deterministic
validation failure. The Stage-S prompt now explicitly requires
`grounding_schema_version` to equal `cloudflare-grounded-wrapper-v2`, and its
version is bumped to `cloudflare-grounded-structurer-v3`. This repair is offline
only in Phase 8.4C.4. The durable Stage-V cache means a future separately
authorized proof requires no new image inference, but one new Stage-S call is
still required.

Hosted qualification run `39917945366` passed on repair commit
`24860d72cde0b20e0bad602bdd23fd08bf4a7f3a`. The qualification used no provider
inference and does not authorize another live activation attempt.

## Phase 8.4C.5 protocol-metadata ownership

The Stage-S contract now separates model-owned content from application-owned
protocol metadata. The model owns only the `payload` and `grounding` body:
extracted text and mathematics, labels, relationships, source-role
interpretation, confidence claims, evidence quotations, and JSON Pointer
mappings remain provider claims. The application owns the wrapper protocol
version plus provider/model identity, prompt and checkpoint versions, request
digests, result digests, usage, and provenance that are independently known at
runtime.

`grounding_schema_version` is no longer requested from the model. The adapter
assembles it deterministically as the exact
`cloudflare-grounded-wrapper-v2` constant, records separate raw provider-body
and assembled-wrapper digests, and then applies the unchanged full internal-v2
validation and grounding gates. Known application metadata unexpectedly emitted
at the provider-body top level is discarded by field name and recorded without
its value; any unknown content-bearing field fails closed.

The Stage-S prompt and cache identity are now
`cloudflare-grounded-structurer-v4`. The Cloudflare transport schema still uses
only `type`, `properties`, `required`, and `items`. The activation workflow also
requires the existing exact Stage-V synthetic cache and accepted transcript
digest; a cache miss fails as `STAGE_V_DURABLE_REUSE_FAILED` without authorizing
a replacement vision inference.

## Phase 8.4C.6 semantic enums and private synthetic diagnostics

Stage-S semantic enums remain model-owned. `evidence[*].kind` retains the exact
production vocabulary: `answer`, `answer_working`, `marking_note`,
`teacher_comment`, `tick`, `cross`, `diagram_entry`, and
`other_visible_annotation`. `mark_changes[*].level` likewise remains a closed
model-semantic enum. Confidence, question association, and interpreted content
also remain model-owned. Request-known constants such as payload schema/page,
visual source, and confirmation policy were audited but left unchanged in this
bounded increment.

The v5 structurer prompt distinguishes Stage-V reading prefixes from output
kinds and explains their bounded semantic use. A pre-validation canonicalizer
performs only Unicode NFKC, trim, ASCII lowercase, whitespace/hyphen-to-
underscore conversion, and repeated-underscore collapse. It accepts the result
only when it exactly matches the existing closed enum; semantic aliases remain
invalid. Applied normalization provenance records only the JSON Pointer and the
safe canonical enum.

Synthetic activation can now persist the parsed raw Stage-S provider body before
internal validation. The private artifact includes fixture identity, Stage-V
transcript digest, structurer model/prompt version, provider-body schema version,
raw provider-body digest, and the synthetic body. Persistence refuses every
privacy classification except `synthetic_test`, scans for credential markers,
uses a private temporary workflow path, and retains the artifact for 14 days.
Sanitized reports expose failure paths, categories, normalization metadata, and
artifact presence without exposing rejected values or evidence content.

## Phase 8.4C.7 composite claim boundary and offline forensic replay

The Phase 8.4C.6 private artifact is preserved as a credential-free regression
fixture with provenance `captured synthetic activation shape`. Its digests match
the captured provider body and durable Stage-V transcript. Under the historical
policy it contains 60 populated leaves, 40 content-bearing leaves, and seven
grounding rows. The first failure is the unknown `prinited_value` leaf. Ignoring
that row exposes 34 missing paths; uniquely repairing it exposes 33. Those
missing paths include 24 image-space coordinates, six question references,
normalized-math duplicates, and a structural visual-presence boolean. The body
also contains a zero-delta mark-change claim.

`cloudflare-composite-claim-boundary-v1` now preprocesses only Cloudflare's
text-only Stage-S output before grounding. Schema version, page, evidence source,
and mark-confirmation policy are application constants. Visual presence and crop
ownership are application-derived. Bounding boxes and independently asserted
normalized mathematics are unavailable to the current text-only Stage S and are
set to null. Evidence kind, mark-change level, and confidence remain model
semantic metadata. Transcription, warnings, and genuinely different mark values
remain model content.

The application derives `visual_content_present` from surviving evidence or
mark-change records and sets model question references to null so the existing
region association assigns the single deterministic crop owner. It discards
non-null model bounding boxes, independently emitted normalized mathematics, and
equal printed/visual mark changes with explicit audit counts. Source-backed
transcription and diagram evidence remain unchanged; spatial rendering continues
to preserve the source crop.

Grounding requirements are generated from the sanitized payload under
`cloudflare-grounding-policy-v3`. Unknown future fields remain content-bearing.
`cloudflare-grounding-pointer-normalizer-v1` may repair only one unique,
one-edit final leaf under the exact same parent and array index. It cannot change
parents, indexes, containers, exempt fields, ambiguous names, or semantic terms.
Grounding rows for nulled, removed, or application-derived fields are removed and
cannot resurrect discarded model content.

The captured body reduces deterministically to 23 populated leaves, five actual
content-bearing transcription claims, five supplied and accepted grounding rows,
and zero missing or unknown rows. The offline replay uses the same assembly,
internal-wrapper, grounding, and production visual-response validators as the
provider adapter and creates a normal successful `ProviderResult` without any
network call.

The Stage-S prompt is `cloudflare-grounded-structurer-v6`; it requires null
bounding boxes, application-owned crop association, null normalized mathematics,
spatial `diagram_entry` guidance, explicit evidence for real mark changes, and no
diagram-number or zero-delta mark changes. Composite checkpoints are version 3.
The Stage-V prompt and durable transcript identity remain unchanged.
