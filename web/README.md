# Teacher pilot web application

Phase 8.0 provides the React + Vite teacher application for the PBHS Mathematics
memo-conversion pilot.

## Supported teacher flow

1. Accept an administrator-issued invitation and choose a private password, or sign in with an approved account.
2. View recent conversions owned by that account.
3. Upload a PDF, DOCX, PNG or JPEG memo up to 50 MB.
4. Create and dispatch a conversion.
5. Follow teacher-friendly progress based on the durable job record.
6. Open the v4.9 Phase 8 pilot review page when teacher judgement is required. The review page supports natural question order, stable skip, staged corrections and one explicit batch recheck.
7. Download private Word and PDF outputs when complete.
8. Retry a conversion that stopped in `failed_retryable`.

## Local development

Use Node.js 22 or later.

```powershell
cd web
npm install
Copy-Item .env.example .env.local
npm run dev
```

Set only:

```text
VITE_SUPABASE_URL
VITE_SUPABASE_PUBLISHABLE_KEY
```

Both are browser-safe project identifiers. Never add the Supabase secret/service-role
key, GitHub token, or AI provider keys to a `VITE_*` variable.

## Tests

```powershell
npm run test:run
```

The tests cover invitation onboarding, strong password guidance, sign-in-only
public access, auth routing, state mapping, upload validation and sequencing,
review handoff, private downloads, retry/terminal failures, RLS assumptions and
client secret checks.

## Trusted staff provisioning

The invitation utility is intentionally outside the browser bundle:

```powershell
cd web
node scripts/provision-staff.mjs --dry-run `
  --email synthetic@example.invalid `
  --display-name "Synthetic Teacher" `
  --role teacher
```

For live state inspection, set `SUPABASE_URL` and a modern `sb_secret_...` key in
`SUPABASE_SECRET_KEY`, only in the trusted process environment. A legacy
`SUPABASE_SERVICE_ROLE_KEY` is accepted temporarily by the provisioning CLI as a
deprecated fallback; it is never preferred and is not accepted by the hosted
validation harness. JSON or CSV can be read with `--input <path>` or from
standard input with `--input -`. Keep private input outside the repository,
preferably under the ignored `provisioning-private/` directory. Never redirect
invitation output into a tracked file.

## GitHub Pages build

The live repository publishes `main:/docs`. Build with production values in the
process environment:

```powershell
$env:VITE_SUPABASE_URL='https://your-project.supabase.co'
$env:VITE_SUPABASE_PUBLISHABLE_KEY='your-publishable-key'
npm run build
```

Vite writes only `docs/teacher-app/` and uses
`/PBHS_MEMO_CONVERTER/teacher-app/` as its base. It does not replace the accepted
review or camera-handoff pages.

See [Phase 8.0 Teacher Pilot Application](../docs/PHASE8_0_TEACHER_PILOT_APP.md) for
the backend contracts, security model, status mapping and pending hosted acceptance.
