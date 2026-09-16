# Architecture Decision Register

## ADR-001 — External runtime
Production runtime is external to the PBHS Google Workspace organisation.

## ADR-002 — GitHub Actions as pilot compute
Heavy Memo Engine jobs run on ephemeral GitHub-hosted Actions runners.

## ADR-003 — Supabase consolidates pilot backend
Phase 0 uses Supabase for Auth, Postgres, private Storage and the lightweight dispatch function.

## ADR-004 — GitHub is not the durable database
Actions runners are disposable compute only.

## ADR-005 — Green is earned
Model-reported confidence cannot make an item Green. Deterministic/evidence gates may force Amber/Red.

## ADR-006 — No invented frozen schema
The missing machine-readable interpretation schema will not be silently reconstructed and labelled as the original v1.0.

## ADR-007 — AI providers are adapters
Provider-specific APIs do not leak into canonical memo data or teacher workflows.

## ADR-008 — No AI in Phase 0
Hosted upload/dispatch/job-state plumbing must be proven before provider integration.
