# Phase 4.5 — Resilient semantic interpretation

A Groq `tool_use_failed` response is treated as a provider/model harness failure,
not as evidence that the memo is invalid.

Changes:
- maps `tool_use_failed` to a retryable provider error
- sends GPT-OSS instructions in one user message
- suppresses returned reasoning and lowers completion budget
- retries a failed multi-candidate batch one candidate at a time
- if a candidate still cannot be safely classified, creates an Amber
  `semantic_provider_unresolved` review exception instead of aborting the job
- exhausted temporary provider failures degrade to review; hard configuration,
  authentication and permission failures remain fatal

No numbering, arithmetic, source-integrity or Green/Amber/Red safety gate is weakened.
