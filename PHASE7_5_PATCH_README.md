# PBHS Memo Converter — Phase 7.5 Main Patch

Current status: **ACCEPTED — Hosted RAW end-to-end acceptance completed successfully.**
See the [accepted baseline](README.md#phase-75-accepted-baseline), dated 2026-09-26.
The patch sequence below is retained as historical documentation of the original
22 September implementation, before later conditional-scoring and supersession fixes.
Do not reapply it to the accepted checkpoint.

Purpose: repair the Drive/GitHub drift discovered on 22 September 2026 and put the locally qualified Phase 7.5 category-specific correction semantics onto the current `main` implementation without redesigning accepted phases.

## What this patch changes

It adds `engine/src/memo_engine/phase7_5.py` and focused Phase 7.5 tests, then makes small guarded edits to:

- `engine/src/memo_engine/corrections.py`
- `engine/src/memo_engine/correction_reinterpretation.py`
- `engine/src/memo_engine/cli.py`
- `.github/workflows/process-memo.yml`

The hosted workflow is also changed to run `python -m pytest -q engine/tests` before the worker. It does **not** change Supabase schema, create a project, touch the unrelated personal project, or introduce a generic correction editor.

## Safe apply sequence

Place the ZIP in the repository root and extract it there. The patch payload is isolated under `patch_payload/`; extraction alone does not overwrite the four existing engine/workflow files.

Run:

```bash
python apply_phase7_5_patch.py --check
python apply_phase7_5_patch.py
python -m pip install "pytest>=8,<9"
python -m pytest -q engine/tests
git diff --check
git diff
```

The patcher checks exact Git blob SHAs for the implementation files it modifies **and** the compatibility files it depends on. If `main` has changed, it aborts instead of applying against an unknown state.

If the tests and diff are clean:

```bash
git add engine/src/memo_engine/phase7_5.py \
        engine/src/memo_engine/corrections.py \
        engine/src/memo_engine/correction_reinterpretation.py \
        engine/src/memo_engine/cli.py \
        engine/tests/test_phase7_5_raw_categories.py \
        .github/workflows/process-memo.yml

git commit -m "Implement Phase 7.5 RAW exception correction semantics"
git push origin main
```

## Historical hosted acceptance plan

Do **not** mark Phase 7.5 accepted after the push or merely because tests pass.

The original plan used `acceptance/PBHS_Phase7_5_Full_RAW_Acceptance_Test_v2.html` for RAW job `a284e625-6a71-43bd-ac81-7679a29de421`. It retained the already-confirmed 11.12.1 → 11.2.1 correction and guided the teacher through eight remaining cause-level corrections, one show-back/confirmation at a time. The accepted run used the later effective-history audit in `docs/phase7-5-review/index.html`.

Version 2 intentionally submits the new Q8.1 and Q10 categories as **typed evidence** so the existing deployed `submit-correction` Edge Function can remain unchanged. Reinterpretation still produces a structured proposal and confirmation is still mandatory.

Phase 7.5 is accepted only after the live audit shows all of the following:

- job `status=complete`, `stage=complete`, `engine_version=phase7.5`;
- no open/awaiting review exceptions;
- canonical `status=render_ready` and computed total `150`;
- 11 major questions with the benchmark subtotals;
- the current effective correction audit is present and consistent, all effective corrections applied, zero application issues, and every superseded correction has a valid `superseded_by` and is unapplied in the current pass;
- deterministic DOCX and PDF render completed;
- DOCX and PDF preflight both passed;
- `phase6_render_complete` event records computed total 150.

The original rule required every confirmed row to have `applied_at`. The later
supersession implementation replaced that rule: historical timestamps are diagnostic
only. See [correction-history acceptance](docs/PHASE7_5_CORRECTION_HISTORY.md).

Hosted acceptance succeeded on 2026-09-26 in run `36212752841`, using commit
`55792320fde6c2c86c62ca85d524a4b0849fe599`: 150 marks, 11 questions, effective
correction history accepted, and hosted DOCX/PDF rendering and preflights passed.
