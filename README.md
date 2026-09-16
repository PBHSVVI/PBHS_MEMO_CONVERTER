# PBHS Mathematics — GDE Memo Builder

External, provider-independent memo conversion system.

## Pilot architecture

- **Frontend:** static web application (target: GitHub Pages)
- **Identity / database / storage / lightweight API:** Supabase
- **Heavy compute:** GitHub Actions
- **Memo Engine:** Python
- **AI:** provider adapters selected by a quota-aware router
- **Project record / benchmark archive:** PBHS Maths Support Google Drive

The production runtime is intentionally external to the PBHS Google Workspace organisation.

## Core product flow

`UPLOAD → CONVERT → REVIEW ONLY IF REQUIRED → DOWNLOAD`

## Non-negotiable contract

**AI interprets. Deterministic code validates, calculates and renders.**

A model may never make an item Green merely by reporting high confidence. Green is earned only after applicable deterministic and evidence-consistency gates pass.

## Phase 0 status

This repository scaffold defines the system boundaries and the first hosted vertical slice. It does **not** yet claim to be the working converter.

See:

- `docs/ARCHITECTURE_V1.md`
- `docs/JOB_STATE_MACHINE.md`
- `docs/PHASE0_SETUP.md`
- `supabase/migrations/0001_core.sql`
- `.github/workflows/process-memo.yml`
- `engine/`
- `contracts/`

## Controlled existing authorities

The project already has controlled documents in PBHS Maths Support:

1. GDE Mathematics Memo Interpretation Schema v1.0
2. GDE Mathematics Memo Rendering Specification v1.0
3. RAW/GOLD Paper 1 benchmark pair
4. RAW/GOLD Paper 2 benchmark pair
5. Phase C live findings

The explanatory schema refers to a machine-readable JSON companion. That JSON file was not found in Drive under its expected filename during Phase 0 setup. Therefore `contracts/gde/README.md` reserves the slot but does **not** invent or silently recreate a frozen v1.0 JSON contract.

## Repository policy

- No school-domain runtime dependency.
- No learner-identifiable data in logs.
- No AI API keys in frontend code.
- No Supabase secret key in frontend code.
- All public tables use RLS.
- Source/output file buckets remain private.
- GitHub Actions receives a `job_id`, not the document contents as workflow input.
- AI providers are adapters, never application architecture.
