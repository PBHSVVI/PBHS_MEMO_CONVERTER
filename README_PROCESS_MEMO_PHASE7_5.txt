PBHS Memo Converter — Phase 7.5 Process Memo workflow update

Upload this ZIP's contents to the repository root, preserving folders and
replacing:

.github/workflows/process-memo.yml

This is the exact workflow change that passed inside the Phase 7.5 Action
runner before GitHub blocked the workflow-generated push.

Changes:
- install pytest alongside engine dependencies;
- run `python -m pytest -q engine/tests` before processing a memo;
- preserve the existing hosted worker and renderer toolchain.

After upload, no new Phase 7.5 patch Action is needed.
