PBHS Memo Converter — Phase 7.5 Action Push Fix v2

Why the previous Action failed
------------------------------
The patch, tests and git diff all succeeded. The final push failed because
the workflow-generated commit included .github/workflows/process-memo.yml.
GitHub refuses to let a workflow token update workflow files unless it has
the separate workflows permission.

This replacement workflow:
- still validates the exact Phase 7.5 baseline;
- still applies the complete patch in the runner;
- still runs all engine tests;
- deliberately restores process-memo.yml before committing;
- commits/pushes only the Phase 7.5 engine + test files.

After this Action succeeds, process-memo.yml will be updated separately by
manual repository upload, which is our established GitHub ZIP method.

Do not confirm the pending 2.2 correction until the engine commit is verified.
