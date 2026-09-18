# Phase 4.4 — Rate-aware Groq routing

This patch addresses real Groq Free-tier 429 responses.

Changes:
- semantic batch size reduced from 16 to 6
- normal inter-batch spacing increased from 15s to 20s
- GPT-OSS reasoning effort set to `low`
- completion ceiling set to 4096 tokens
- rationale requested as one short sentence
- HTTP 429 no longer immediately fails the memo
- worker reads Groq `retry-after` and `x-ratelimit-reset-tokens`
- worker waits for the provider-defined reset window and retries automatically
- bounded fallback backoff is used when rate-limit headers are absent
- maximum automatic 429 retries defaults to 5

No deterministic gate, source content, privacy rule, model permission, or semantic
shorthand constraint is weakened.
