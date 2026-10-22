# Phase 8.4B live free-provider benchmark

Date: 2026-10-22

Status: **INCOMPLETE — Cloudflare activation blocked; Stage 1B is not ready.**

This qualification used only programmatically generated images. It did not read
Supabase, create or resume a memo job, access Storage, or send PBHS/teacher/learner
content to any provider.

## Configuration preflight

The three required GitHub secrets were present by name. Their values were never
read into logs or reports. `CLOUDFLARE_ZERO_COST_CONFIRMED` and
`MISTRAL_ZERO_COST_CONFIRMED` were both `true`.

The repository's live `MISTRAL_SCHOOL_PRIVATE_APPROVED` value was unexpectedly
`true`, although the Phase 8.4B instruction identified it as `false`. Phase 8.4B
did not change the variable. The isolated benchmark forced it to `false`, sent
only synthetic data, and proved that the fabric made no Mistral request for a
synthetic payload carrying the `school_private` policy label.

`MEMO_MISTRAL_VISION_MODEL` remains unset. It was deliberately not set while the
repository privacy variable is in the unexpected state, so Mistral cannot become
an active production visual route merely because its key exists.

## Cloudflare

The registry model ID was already the official
`@cf/qwen/qwen3.8-27b` identifier. The first live test exposed an adapter-route
defect: the account's OpenAI-compatible `/ai/v1/chat/completions` route returned
HTTP 404 for this model. The adapter was narrowed to Cloudflare's documented
native endpoint:

`/client/v4/accounts/<account>/ai/run/@cf/qwen/qwen3.8-27b`

The native endpoint also returned HTTP 404 with the configured account. The
request reached Cloudflare, but no structured result was produced. This is now an
account/model availability or account-ID configuration blocker rather than an
unresolved model-string or route-generation defect. Live Cloudflare testing
stopped without retries or paid fallback.

Three Cloudflare inference requests were made across diagnosis: two against the
old OpenAI-compatible route and one against the corrected native route. No
benchmark fixture or live cache-reuse result was accepted.

Cloudflare is **not activated** and is **not ready** as the PBHS school-private
fallback.

## Mistral

The authenticated model-list request returned 53 account-visible models. The
smallest current documented multimodal candidate present was selected:

`ministral-3b-2512`

One preflight and four fixture requests were made through the real Phase 8.4A
adapter. All five authenticated successfully, used standard service tier, and
returned schema-valid normalized results. No rate or quota headers were exposed.

| Fixture | Result | Observed behavior |
| --- | --- | --- |
| Numeric working | partial | Schema valid; one evidence item, but required values and answer role were not recovered |
| Probability tree | fail | Schema valid; no evidence returned |
| Venn diagram | partial | All four region values recovered without invented values; diagram/spatial role was not classified correctly |
| Question vs solution | partial | Schema valid; one evidence item, but answer values and expected role were not recovered |

Observed inference latency was 679–2,008 ms. Mean latency across the preflight and
four fixtures was approximately 1,158 ms. No hallucinated numeric values were
detected by the bounded scorer.

Mistral is **technically qualified for synthetic adapter use**. The selected 3B
model is not recommended as a quality fallback on this benchmark, and it is not
approved for school-private data.

## Policy and regression evidence

- Groq was deliberately skipped to preserve free quota.
- Controlled Groq/Cloudflare-disabled routing selected the real Mistral adapter.
- The isolated `school_private` policy test denied Mistral with zero provider calls.
- The controlled all-provider-open test returned infrastructure deferral with no
  paid route, fabricated result, or teacher-review item.
- Live cache reuse could not be demonstrated because Cloudflare never produced a
  successful result and the five-call Mistral ceiling had already been reached.
  The mocked cross-provider cache regression remains green.
- Local focused Phase 8 suites: 93 passed, 1 skipped.
- Local full Python suite: 598 passed, 4 skipped.
- Hosted qualification run `39743977248` passed on
  `e76010edd43f5051bdfc800cd294adaecc7d8ce6`:
  Slice 1 15 passed; Slice 2 8 passed; Slice 3 23 passed; Slice 4 29 passed;
  Phase 8.4A 16 passed. Hosted DOCX and PDF spatial preflight passed.

## Zero-cost result

The benchmark used only providers whose repository zero-cost confirmations were
set. Transport retries were disabled, Groq was not called, no paid fallback was
configured, and every controlled exhausted/unavailable case deferred. Estimated
billable spend is `R0.00 / $0.00`. No billing API or account ledger was queried,
so this record does not claim independent billing-ledger verification.

## Required remediation before Stage 1B

1. Correct and re-verify the repository privacy variable so
   `MISTRAL_SCHOOL_PRIVATE_APPROVED=false` is true in repository configuration.
2. Verify the configured Cloudflare account ID belongs to the token and that the
   account exposes `@cf/qwen/qwen3.8-27b` through Workers AI Free.
3. Rerun one Cloudflare synthetic preflight against the native endpoint. Continue
   the remaining fixtures and live cache proof only after that succeeds.
4. Keep production school-private order as Groq then defer until Cloudflare is
   live-qualified. Do not add Mistral to that route.

Recommended current orders:

- School-private: `Groq -> defer`
- Synthetic: `Groq -> Mistral (technical/benchmark use) -> defer`

