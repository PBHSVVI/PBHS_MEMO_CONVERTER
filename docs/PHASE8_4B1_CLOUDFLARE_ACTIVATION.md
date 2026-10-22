# Phase 8.4B.1 Cloudflare account diagnostic and activation

Date: 2026-10-22

Status: **BLOCKED — account/model discovery passes, but live inference did not
produce a usable provider result.**

## Corrected-account rerun

Workflow run `39766916221` used commit
`053beaa5641d9f8084dfc4762510012591e29ffc` after the repository secret was
corrected. It established:

- the account ID has the required 32-character hexadecimal format;
- the token remains active through the user-token verification endpoint;
- account-scoped model search returned HTTP 200, proving the token can read
  Workers AI models for this account;
- the account-scoped token-verification endpoint returned HTTP 401 for this
  token type, so model search is the relationship proof;
- 73 models are visible to the account;
- both `@cf/qwen/qwen3.8-27b` and
  `@cf/google/gemma-4-26b-a4b-it` are visible;
- Gemma was selected from the bounded free-compatible vision allowlist;
- the live adapter produced no successful normalized result, so cache reuse and
  live failover were not accepted;
- the provider-model repository variable remains unset.

The diagnostic made two inference calls. The first unsuccessful visual extraction
returned a deferred checkpoint instead of raising. The original harness then
mistakenly entered its cache-reuse step, which caused one additional unsuccessful
call. The harness now stops after one unsuccessful preflight, records the safe
provider failure fields, and skips cache reuse. No further live inference was made
after this defect was identified.

## Initial hosted diagnostic

Workflow run `39756392939` used commit
`7b396fcdbc797e4f100c3ad92eceacb821796784` and established:

- the configured Cloudflare API token is active (`HTTP 200`, `success=true`);
- `MISTRAL_SCHOOL_PRIVATE_APPROVED=false` and
  `CLOUDFLARE_ZERO_COST_CONFIRMED=true` were enforced before provider access;
- the configured account ID contains 31 hexadecimal characters instead of the
  required 32;
- Cloudflare returned `HTTP 404`, internal code `7003`, for account-scoped token
  verification and model search because it could not route the malformed account
  path;
- the earlier Qwen `404` therefore did not establish whether
  `@cf/qwen/qwen3.8-27b` is visible or callable for the intended account;
- account-visible model discovery, live synthetic inference, checkpoint reuse and
  live failover remain unexecuted;
- total new Cloudflare inference calls were zero and spend remained R0.00 / $0.00.

The run's initial sanitized artifact was removed because Cloudflare repeated the
malformed account identifier in its safe error text. The diagnostic now redacts
account identifiers and rejects malformed identifiers before making an
account-scoped request.

## Configuration and activation boundary

The provider registry centrally accepts only these explicitly approved
Workers-Free-compatible Cloudflare vision models:

- `@cf/google/gemma-4-26b-a4b-it`
- `@cf/qwen/qwen3.8-27b`

The selected production model is supplied through the repository variable
`MEMO_CLOUDFLARE_VISION_MODEL`. That variable must remain unset until a corrected
32-character `CLOUDFLARE_ACCOUNT_ID` passes model search and the one-call hosted
synthetic qualification.

No Workers Paid plan, Unified Billing, AI Gateway credits, overage, production
memo job, Supabase data or protected job was accessed or changed.

## Required next action

Replace the `CLOUDFLARE_ACCOUNT_ID` repository secret with the exact 32-character
account ID belonging to the active token. Then rerun
`Phase 8.4B.1 Cloudflare Activation`. A successful run must discover an approved
account-visible vision model, complete exactly one synthetic inference, reuse the
checkpoint with zero additional inference calls, and prove the test-only
Groq-unavailable to Cloudflare route before the model variable is activated.
