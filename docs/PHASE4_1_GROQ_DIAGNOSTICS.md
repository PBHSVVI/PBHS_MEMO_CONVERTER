# Phase 4.1 — Groq 403 diagnostics

This hotfix does not change the semantic pipeline or send additional source content externally.

It parses Groq's JSON error body and promotes only bounded, safe provider diagnostics
into the durable worker error. It distinguishes organization-level and project-level
model-permission blocks when Groq returns those codes.

The API key and semantic prompt are never logged.
