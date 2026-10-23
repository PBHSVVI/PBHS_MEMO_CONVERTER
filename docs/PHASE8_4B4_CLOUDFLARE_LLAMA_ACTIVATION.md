# Phase 8.4B.4 Cloudflare Llama structured-vision activation

> **Later qualification result (2026-10-23):** Phase 8.4B.5's single authorized
> live structured-vision inference received HTTP 400 before a model envelope was
> returned. Llama 3.2 11B Vision is therefore no longer classified as
> `structured_json` or `structured_visual`. See
> `PHASE8_4B5_CLOUDFLARE_LLAMA_LIVE_PROOF.md`. The historical implementation and
> offline qualification notes below are retained as the Phase 8.4B.4 record.

Date: 2026-10-22

Status: **HOSTED QUALIFIED; LIVE ACTIVATION STOPPED AFTER TERMS RESPONSE PARSING
DEFECT. A NEW EXPLICIT LIVE AUTHORISATION IS REQUIRED.**

## Model decision

Gemma 4 and Qwen 3.8 remain known Cloudflare vision models, but they are not
classified as `structured_visual`. The Gemma activation attempts showed that
accepting an image does not establish reliable JSON Schema output.

Cloudflare lists `@cf/meta/llama-3.2-11b-vision-instruct` as vision-capable and
as a JSON Mode model. The provider registry therefore records model-level
capabilities and limits Cloudflare structured visual routing to that model.
Teacher workflow code does not contain a model-specific choice.

## Contract

The Llama transport sends the prompt in `messages`, the image as a top-level
data URI, `stream=false`, and the raw JSON Schema object at
`response_format.json_schema`. Existing Cloudflare native extraction continues
to accept `result.response` and `result.choices[0].message.content`.

The documented `JSON Mode couldn't be met` condition is classified as a
non-retryable `content_request` inability. It does not trigger prose salvage,
fabricated JSON, provider shopping, teacher review noise, or paid fallback.

## Offline qualification

- Llama contract suite: 24 passed
- provider/Cloudflare focused suites: 59 passed
- Slice 1: 15 passed
- Slice 2: 7 passed, 1 skipped locally
- Slice 3: 23 passed
- Slice 4: 29 passed
- full Python after the offline acknowledgement repair: 641 passed, 4 skipped
- Python compilation: passed
- `git diff --check`: passed

The activation workflow permits exactly one terms-acceptance run-path request
and one synthetic inference request, with all HTTP retries disabled. It uses no
PBHS, teacher, learner, Supabase, Storage, or production memo data.

## Hosted and live result

Hosted Phase 8 qualification run `39824189266` passed against commit
`598364dfca90cf76208f46d8311bf8dc5aceee42`. The first hosted runner was
cancelled after its dependency installation stalled; it never reached tests or
provider actions.

Activation run `39824349292` confirmed that Llama is visible among 73 account
models. It made exactly one Meta terms request and no synthetic inference. The
terms endpoint returned a 2xx JSON acknowledgement whose root was not an object;
the harness then raised `AttributeError` by assuming an envelope with `.get()`.
No response content or credential was logged.

The harness now treats any decoded non-object returned by the exact agreement
request as a successful 2xx acknowledgement while still respecting explicit
`success=false` object envelopes. This repair is offline only. The agreement
request was not repeated, the Llama model variable remains unset, and a future
synthetic inference requires separate explicit authorization.
