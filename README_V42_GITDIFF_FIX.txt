PBHS Memo Converter — v4.2 Git diff fix

The first v4.2 Action failed only because git diff --check detected:
  engine/tests/test_phase7_5_raw_categories.py:393: new blank line at EOF

The patch itself applied successfully.
33 tests passed, 1 skipped.
The browser JavaScript syntax check also passed.

This replacement workflow normalizes the patched files to exactly one newline
at EOF before running git diff --check.

Upload this ZIP at repo root, replacing:
  .github/workflows/apply-phase7-5-conditional-scoring-fix.yml

Then rerun:
  Actions -> Apply Phase 7.5 Conditional Scoring Fix -> Run workflow
