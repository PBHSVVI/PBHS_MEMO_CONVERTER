# Supabase Phase 0 — Live State

## Project

- Organization: Pretoria Boys High School Mathematics
- Supabase project: PBHSVVI's Project
- Project ref: `njrqiurqljwtuqrvguhj`
- Region: `eu-west-2`
- Project URL: `https://njrqiurqljwtuqrvguhj.supabase.co`

## Applied migrations

1. `phase0_core`
2. `phase0_storage_and_tenant_hardening`
3. `phase0_foreign_key_indexes`

## Live resources

- Tables: `jobs`, `job_events`, `exceptions`, `corrections`
- Private Storage bucket: `memo-files`
- Edge Function: `dispatch-memo`
- Edge Function auth: authenticated Supabase user required (`verify_jwt = true`)
- Security advisor after deployment: no findings

## Storage namespace

```text
{user_id}/{job_id}/
  source/original.ext
  pages/page-001.png
  internal/extraction.json
  internal/canonical.json
  internal/validation.json
  corrections/{correction_id}.ext
  output/memo.docx
  output/memo.pdf
```

Authenticated browser users may read their own namespace. Browser writes are restricted to
`source/` and `corrections/`. Backend workers use a Supabase secret key and may write internal
and output paths.

## Secrets still required

Do not commit values for these.

### Supabase Edge Function secret

- `GITHUB_TOKEN` — fine-grained GitHub token with Actions: write for
  `PBHSVVI/PBHS_MEMO_CONVERTER`

Optional defaults already built into the function:

- `GITHUB_REPOSITORY=PBHSVVI/PBHS_MEMO_CONVERTER`
- `GITHUB_REF=main`

### GitHub Actions repository secrets

- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`

Use the modern `sb_secret_...` server-side key, never a publishable key, for
`SUPABASE_SECRET_KEY`.
