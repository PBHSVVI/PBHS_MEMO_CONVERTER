# Phase 0 Setup

## Goal

Prove hosted execution with no local administrator rights and no always-on PC.

```text
sign in
  -> upload file
  -> create queued job
  -> authenticated dispatch
  -> GitHub Action starts
  -> Python worker reads job
  -> worker reports success/failure
  -> browser reads durable status
```

No AI is required to pass Phase 0.

## GitHub prerequisite

Create or expose a private repository to the ChatGPT GitHub connection.

Current connector result:
- authenticated GitHub profile exists;
- zero accessible repositories;
- zero installed accounts exposed.

Recommended repository name:

`pbhs-gde-memo-builder`

## Supabase prerequisite

Create a dedicated Memo Builder project rather than reusing an unrelated project.

## Secrets

Frontend:
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`

Supabase Edge Function:
- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`
- `GITHUB_REF`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SECRET_KEY`

GitHub Actions:
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`

Later AI:
- one secret per provider.

## Phase 0 acceptance tests

1. Unauthorized visitor cannot read jobs.
2. User A cannot read User B's job.
3. User A cannot read User B's files.
4. Client cannot write worker-only job states.
5. Dispatch rejects a job not owned by caller.
6. Dispatch rejects a job not in `queued`.
7. Duplicate dispatch cannot process the same job twice.
8. Workflow receives only a job UUID.
9. Worker can update durable state with server credentials.
10. Worker failure produces a durable failure state.
11. No source content appears in Actions logs.
12. Browser refresh/closure does not lose job progress.

## Supabase 2026 note

New Supabase projects may require explicit Data API exposure/grants for newly created tables. Verify Data API exposure/settings after project creation before debugging frontend access.
