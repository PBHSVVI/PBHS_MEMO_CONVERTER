# Phase 8.4B.4 Cloudflare Llama structured-vision activation

Date: 2026-10-22

Status: **OFFLINE QUALIFIED; HOSTED AND LIVE QUALIFICATION PENDING.**

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

- Llama contract suite: 20 passed
- provider/Cloudflare focused suites: 55 passed
- Slice 1: 15 passed
- Slice 2: 7 passed, 1 skipped locally
- Slice 3: 23 passed
- Slice 4: 29 passed
- full Python: 637 passed, 4 skipped
- Python compilation: passed
- `git diff --check`: passed

The activation workflow permits exactly one terms-acceptance run-path request
and one synthetic inference request, with all HTTP retries disabled. It uses no
PBHS, teacher, learner, Supabase, Storage, or production memo data.
