PBHS Memo Converter — Review UX v3

This overlay adds:
1. acceptance/PBHS_Phase7_5_Full_RAW_Acceptance_Test_v3.html
   - evidence-first review;
   - browser visual preview of the original uploaded DOCX/PDF/image;
   - zoom, drag-to-pan and refocus;
   - extracted immutable source context fallback;
   - safe pause/resume from Supabase state;
   - resumes an already-pending correction instead of creating a duplicate.

2. .github/workflows/apply-phase7-5-patch.yml
   - applies the Phase 7.5 patch package that is already present in the repo;
   - verifies the exact baseline;
   - runs the full engine test suite;
   - commits/pushes the actual engine changes to main.

Important:
- The current live RAW job has a pending 2.2 proposal. Do not confirm it until the Apply Phase 7.5 Patch workflow has succeeded.
- Pausing/reloading does not discard the pending proposal.
- v3 is a hosted acceptance/prototype review surface. The evidence-first review and pause/resume behaviours are intended to be carried into the production teacher UI.
