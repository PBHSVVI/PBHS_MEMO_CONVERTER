# Phase 4.2 — Groq transport hotfix

The worker uses Python urllib. Groq is fronted by Cloudflare, and the default
`Python-urllib/<version>` User-Agent can be rejected at the edge with HTTP 403
before Groq's normal API error layer is reached.

This hotfix adds explicit `Accept` and `User-Agent` headers to Groq requests.

No memo payload, semantic contract, privacy mode, deterministic rule, or model
selection is changed.
