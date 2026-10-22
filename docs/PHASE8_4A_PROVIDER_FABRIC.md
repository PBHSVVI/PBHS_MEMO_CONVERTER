# Phase 8.4A zero-cost provider fabric

## Invariant

The memo worker may use only capacity that has been explicitly configured as
`free_only`. It never selects a provider/model marked as requiring a paid plan or
allowing automatic overage. When eligible free capacity is unavailable, the job
is checkpointed and moved to the existing retryable visual-infrastructure failure
state. The engine does not buy capacity, use prepaid gateway credits, or route to
a paid fallback.

## Provider-neutral contract

`ProviderTaskRequest` describes the task rather than an API endpoint. It carries
the task and prompt versions, privacy classification, question/page ownership,
source and crop digests, bounded crop bytes, and the required response schema.

`ProviderResult` contains the provider/model identity, task type, normalized
structured result, latency, request attempt, safe usage/quota metadata, result
digest, and redacted route attempts. Provider-specific JSON is consumed inside
the adapter and does not enter canonical processing.

The contract currently declares `visual_interpretation` and
`semantic_classification`. Phase 8.4A routes visual interpretation through the
fabric and leaves the established Groq semantic path unchanged.

## Registry and current adapters

The central registry records capabilities, priority, credential requirements,
free-only plan mode, privacy policy, and enabled state.

| Provider | Initial visual model | School-private eligibility | Notes |
| --- | --- | --- | --- |
| Groq | `qwen/qwen3.8-27b` | allowed | Existing adapter, now available through the shared visual fabric |
| Cloudflare Workers AI | `@cf/qwen/qwen3.8-27b` | allowed | Direct account REST API; the free-model allowlist and `free_only` plan guard must both match |
| Mistral Free | Explicit `MEMO_MISTRAL_VISION_MODEL` configuration | denied by default | No default model is assumed; requires an approved current multimodal Free-mode model and explicit privacy approval for school-private data |

Cloudflare uses the model's direct account Workers AI
`/ai/run/@cf/qwen/qwen3.8-27b` endpoint. The adapter does not set
an AI Gateway ID and therefore cannot opt into AI Gateway prepaid credits or
Unified Billing. Its configured model must remain in the code-reviewed free model
allowlist.

Mistral is eligible for `synthetic_test` when configured. A key alone never makes
it eligible for `school_private`.

## Routing, failover, and circuits

The default order is centrally configurable and initially resolves to Groq,
Cloudflare, then Mistral. Eligibility requires all of the following:

1. enabled provider and required capability;
2. supported privacy classification;
3. `free_only` plan mode with no paid-plan or overage flag;
4. an explicit zero-cost account confirmation flag where required;
5. configured credentials;
6. available provider-specific circuit;
7. no known exhausted free quota.

Capacity, timeout, suitable 5xx, authentication/configuration, and provider
availability failures open only that provider's circuit and allow the next
eligible free provider to run. A crop-specific content rejection remains a
single content result and is not shopped across providers.

Safe telemetry records attempted provider/model, decision, error class, retry
delay, and normalized quota fields. It never records credentials, authorization
headers, crop bytes, or signed URLs.

## Cache behavior

Accepted region results retain source/crop digests, task/prompt/schema versions,
provider/model, and result digest. A retry reuses every compatible successful
region regardless of which provider produced it and starts at the first unresolved
region. Failed provider attempts remain operational telemetry and never create a
second accepted evidence result.

## Controlled activation

Do not activate a provider until its account has been checked for a genuinely
free plan with no billing-backed overage.

Cloudflare activation requires:

- GitHub secret `CLOUDFLARE_ACCOUNT_ID`;
- GitHub secret `CLOUDFLARE_AI_API_TOKEN` scoped to Workers AI inference;
- `CLOUDFLARE_WORKERS_AI_PLAN_MODE=free_only`;
- repository variable `CLOUDFLARE_ZERO_COST_CONFIRMED=true` only after the
  account review below;
- an account review confirming Workers Paid, Unified Billing, prepaid AI Gateway
  credits, and paid overage are not enabled.

Mistral activation requires:

- GitHub secret `MISTRAL_API_KEY` from a Free-mode account;
- repository variable `MEMO_MISTRAL_VISION_MODEL` set to a currently supported
  multimodal model available on that Free-mode account;
- `MISTRAL_PLAN_MODE=free_only`;
- repository variable `MISTRAL_ZERO_COST_CONFIRMED=true` only after confirming
  the account is Free mode with no billing-backed overage;
- repository variable `MISTRAL_SCHOOL_PRIVATE_APPROVED=true` only after the
  required privacy/opt-out condition has been reviewed and approved.

The existing Groq route uses `GROQ_API_KEY`, `GROQ_PLAN_MODE=free_only`, and the
existing production assertion `GROQ_ZERO_COST_CONFIRMED=true`.

Activation must begin with synthetic tests. No real PBHS memo should be sent to a
new provider until the provider's free-plan and privacy gates have passed a
separate controlled review.

## Adding another provider

Add one registry entry and one adapter that converts the shared task request into
the vendor request and returns a `ProviderResult`. Keep response parsing inside
the adapter, map errors to the existing provider taxonomy, add an explicit
free-only and privacy policy, and qualify routing, circuit independence, cache
reuse, and content-error behavior with mocked responses before activation.

Provider endpoint contracts used by these adapters are documented by
[Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)
and [Mistral Chat Completions](https://docs.mistral.ai/api/).
