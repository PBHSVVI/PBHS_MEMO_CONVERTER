# Phase 8.4B.5 Cloudflare Llama live proof

Date: 2026-10-23  
Starting baseline: `9c663b55ff7f089989ce808f1729e8ddad3f8919`  
Bounded proof harness: `103ee2e5fc1b1d0ac39493671e0d7f7dd3ee03a6`  
GitHub Actions run: `39903216429`

## Result

**NOT QUALIFIED — structured visual activation did not pass.**

The phase issued zero Meta agreement requests and exactly one new Cloudflare
inference request. The request used only the existing deterministic synthetic
image for `10/250 = 1/25 = 0.04 = 4%`, with privacy classification
`synthetic_test`. It used `@cf/meta/llama-3.2-11b-vision-instruct`, the production
visual-evidence schema, top-level image transport, `stream=false`, and zero
provider retries.

Cloudflare rejected the inference with HTTP 400 before returning a native model
response envelope. The safe error classification was `content_request`; no JSON
content was available to parse or validate. Consequently there is no normalized
`ProviderResult`, content-quality result, checkpoint, cache replay, or cached
failover proof.

The failure is consistent with Cloudflare's current JSON Mode documentation:
the documented supported-model list does not include Llama 3.2 11B Vision. The
model remains vision-capable, zero-cost-gated, and privacy-eligible, but it is no
longer classified as `structured_json` or `structured_visual` in the provider
registry. This prevents it from receiving production structured visual tasks.

## Safety and cost

- Meta agreement calls in Phase 8.4B.5: `0`
- Cloudflare inference calls in Phase 8.4B.5: `1`
- Groq, Mistral, Gemma, and Qwen live calls: `0`
- Retries: `0`
- Paid features enabled: `false`
- Recorded provider spend: `R0.00 / $0.00`
- Production, Supabase, Storage, teacher, learner, and memo data accessed: `false`
- Protected jobs accessed or mutated: `false`

`MEMO_CLOUDFLARE_VISION_MODEL` was not set. The school-private route therefore
remains `Groq -> defer`; Mistral remains excluded because
`MISTRAL_SCHOOL_PRIVATE_APPROVED=false`.

Another live provider call requires separate authorization. Phase 8.4B.5 does
not permit a retry after this failure, and Fresh Hosted Regression Stage 1B is
not ready.
