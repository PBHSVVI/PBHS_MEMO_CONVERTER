# PBHS Memo Converter — Phase 7.5 Main Patch

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

## Hosted acceptance

Do **not** mark Phase 7.5 accepted after the push or merely because tests pass.

Use `acceptance/PBHS_Phase7_5_Full_RAW_Acceptance_Test_v2.html` for the real RAW job `a284e625-6a71-43bd-ac81-7679a29de421`. It retains the already-confirmed 11.12.1 → 11.2.1 correction and guides the teacher through the eight remaining cause-level corrections, one show-back/confirmation at a time.

Version 2 intentionally submits the new Q8.1 and Q10 categories as **typed evidence** so the existing deployed `submit-correction` Edge Function can remain unchanged. Reinterpretation still produces a structured proposal and confirmation is still mandatory.

Phase 7.5 is accepted only after the live audit shows all of the following:

- job `status=complete`, `stage=complete`, `engine_version=phase7.5`;
- no open/awaiting review exceptions;
- canonical `status=render_ready` and computed total `150`;
- 11 major questions with the benchmark subtotals;
- all confirmed corrections have `applied_at`;
- deterministic DOCX and PDF render completed;
- DOCX and PDF preflight both passed;
- `phase6_render_complete` event records computed total 150.

Until that hosted run succeeds, Phase 7.5 remains **candidate / hosted acceptance pending**.
