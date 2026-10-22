# Phase 8.4B.2 Cloudflare native request/response contract

Date: 2026-10-22

Status: **IMPLEMENTED AND OFFLINE/HOSTED QUALIFIED; LIVE NORMALIZATION REPROOF
REMAINS REQUIRED.**

## Contract repair

The former Cloudflare adapter reused two OpenAI-compatible assumptions:

1. It sent `response_format.json_schema` as a `name` / `strict` / `schema`
   wrapper. Cloudflare's native JSON Mode requires the JSON Schema object itself
   at `response_format.json_schema`.
2. It sent the native `/ai/run` response through the shared
   `choices[0].message.content` parser. Cloudflare documents native output under
   `result.response`, with usage under `result.usage`.

The adapter now sends the schema directly and uses a Cloudflare-specific payload
extractor. Groq and Mistral retain their existing OpenAI-compatible contracts.
Image transport remains a text content part plus an `image_url` data URI part.

The extractor accepts a JSON string or already-decoded object, requires the
normalized value to be an object, rejects invalid JSON and scalar/list results,
preserves `result.usage`, and maps `success=false` through provider failure
handling. Safe diagnostics contain only status, provider error metadata,
result-key names, response type/path and normalization stage.

## Live result

Workflow run `39768718919` used commit
`3ca2464fc3a7918b9aa9727b0cb29cde91b73bc3` and made exactly one Cloudflare
inference request to `@cf/google/gemma-4-26b-a4b-it`.

Cloudflare returned HTTP success with `success=true`. The safe envelope showed
that `result` existed with these keys only:

- `choices`
- `created`
- `id`
- `model`
- `object`
- `usage`

This account/model therefore returned an OpenAI-shaped completion inside the
native Cloudflare envelope at `result.choices[0].message.content`, rather than
the documented `result.response` variant. The response content itself was not
logged. The initial Cloudflare-specific extractor rejected the safe shape as
`AI_PROVIDER_INVALID_RESPONSE` at `cloudflare_native_envelope`.

The extractor was subsequently extended offline to accept both native-envelope
variants explicitly while remaining separate from the shared Groq/Mistral
parser. No second live request was made. Consequently live normalized
`ProviderResult`, checkpoint reuse and failover acceptance remain unproven, and
`MEMO_CLOUDFLARE_VISION_MODEL` remains unset.

Provider spend remained R0.00 / $0.00. No paid feature, Mistral call, production
memo job, Supabase data, Storage data or protected historical job was accessed
or changed.
