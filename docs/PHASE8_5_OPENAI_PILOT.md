# Phase 8.5 OpenAI pilot

The OpenAI route is scoped to the existing Stage 1B job. GitHub Actions reads the project credential from `OPENAI_API_KEY`. The normal authenticated Teacher App retry is the entry point. The worker verifies the source digest and all six previously successful crop digests before it sends an unresolved region. The existing Groq and Cloudflare routes retain their free-only requirements. Mistral remains excluded from school-private traffic.

## Account and privacy gates

- Verify that the dedicated API project belongs to the organization receiving the subscription grant. Confirm an available included balance, disabled automatic recharge, no purchased-credit or paid fallback, and the actual project spending limit. The project credential can check model access. Account owners verify billing and data controls in the Platform dashboard.
- Set the verified, non-secret `MEMO_OPENAI_ORGANIZATION` and `MEMO_OPENAI_PROJECT` repository variables. Set `MEMO_OPENAI_INCLUDED_CREDIT_CONFIRMED=true` only after verifying the billing conditions. Recheck those conditions before using the pilot again after a credit renewal or settings change.
- Dispatch `Phase 8 Quality Hosted Qualification` with `openai_check=access` for a catalogue GET. `openai_check=synthetic` makes at most one Luna visual and one Luna semantic inference using generated data. An already reserved synthetic slot cannot be used again.
- Set `MEMO_OPENAI_SCHOOL_PRIVATE_APPROVED=true` only after a school decision for this project and its applicable data controls. After the synthetic qualification passes, set `MEMO_OPENAI_ENABLED=true` and use **Retry conversion** on the existing pilot. `store=false` disables response application-state persistence. Standard abuse-monitoring retention can still apply. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)

## Request and usage controls

Luna uses the Responses API with low reasoning effort and Standard processing. Visual requests keep the original crop bytes and use high detail. Structured Outputs enforce the transport schema, and the worker checks results against the full existing application schema. Semantic work uses the existing shorthand checks and review path. This qualification does not enable a second OpenAI model.

Before any inference, the worker checks the selected model, text and schema sizes, conservative image patch count, and the output ceiling that includes reasoning tokens. It creates a unique immutable reservation in private PBHS Storage. The same ledger covers the synthetic checks and pilot attempts. Each of 100 slots can authorize a single call with at most $0.02 in reserved usage. A missing receipt or uncertain transport result consumes its reservation. Slots are never recycled, including after a crash or concurrent retry.

Private receipts contain provider-reported token counts when available, elapsed time, and cost estimates using Standard input, cache-read, cache-write and output rates. The estimate counts reasoning tokens inside output tokens. The conservative estimate uses the cache-write rate when write telemetry is unavailable. These estimates can be compared with organization usage after reporting catches up. [Luna model and pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)
