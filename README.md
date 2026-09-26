# PBHS Mathematics — GDE Memo Builder

External, provider-independent memo conversion system.

## Phase 7.5 Accepted Baseline

**ACCEPTED — Hosted RAW end-to-end acceptance completed successfully.**

Accepted on **2026-09-26** for RAW job `a284e625-6a71-43bd-ac81-7679a29de421`.
The accepted implementation checkpoint is commit
`55792320fde6c2c86c62ca85d524a4b0849fe599`, exercised by
[Process Memo run 36212752841](https://github.com/PBHSVVI/PBHS_MEMO_CONVERTER/actions/runs/36212752841)
with conclusion `success`: **58 hosted tests passed on Python 3.13.15**.

- Job: `complete / complete`, engine `phase7.5`; canonical `render_ready`, validation passed, zero active review exceptions.
- Result: **150 marks across 11 major questions**. Q1–Q11 subtotals: **23, 26, 4, 14, 8, 13, 20, 13, 8, 5, 16**.
- Correction history: **13 confirmed, 10 effective, 3 superseded, 10 effective applied, 0 application issues**; correction audit has zero failures/issues.
- Hosted rendering: DOCX and PDF preflights passed; `phase6_render_complete` records total 150; both `memo.docx` and `memo.pdf` exist.
- DOCX: **148,945 bytes**, **253/253 native math elements**. PDF: **372,165 bytes**, **11 pages**, required glyphs present and fonts embedded.

The historical incorrect correction `473f7290-4ce4-4d8c-a269-20705d92de7a`
remains confirmed and auditable, non-effective and unapplied in the current pass,
superseded by `ab07718f-367b-4bab-a9c4-4c066060d64f`. All superseded entries have
valid `superseded_by` links and all effective corrections applied. See
[effective correction history](docs/PHASE7_5_CORRECTION_HISTORY.md) for the acceptance rule.

This checkpoint incorporates the later conditional-scoring recovery, correction
supersession (`b730834ee7c4963265e5f9fccbf78642f378e929`), and effective-history
review acceptance alignment (`55792320fde6c2c86c62ca85d524a4b0849fe599`). Earlier
patch guides and local qualification records remain historical implementation notes;
they are not instructions to reapply patches or create corrections for this accepted job.

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

## Historical Phase 0 scaffold

At Phase 0, the repository scaffold defined the system boundaries and the first hosted vertical slice; it did not yet claim to be a working converter. The current accepted checkpoint is recorded above.

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
