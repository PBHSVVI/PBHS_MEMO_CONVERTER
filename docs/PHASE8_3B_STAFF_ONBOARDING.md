# Phase 8.3B — Secure Staff Invitation Foundation

Status: local implementation complete with hosted synthetic Auth/RLS validation
on `wgkydsildfmbqzvicuwm`. The frontend and utility have not been pushed or
deployed. No real PBHS staff have been provisioned.

## Architecture

Staff onboarding is invitation-only. A trusted administrator runs
`web/scripts/provision-staff.mjs` with staff identity, application role, and any
HOD subject scope supplied at runtime. The utility uses the Supabase Admin API to
generate a one-time `invite` action link without invoking Supabase SMTP. Once it
has the Auth UUID, it creates the matching `department_profiles` row through the
trusted service role.

The action link redirects to:

`https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=invite`

The Teacher App displays the PBHS crest, safe name and email, then asks the
teacher to choose and confirm a password. After Auth accepts the password, the
invite session is signed out and the normal Sign In view confirms that setup is
complete. The app exposes no public signup control.

## Authorization boundary

`department_profiles` remains the application authorization source of truth.
The browser cannot read or change it. Role, HOD scope, and active state are never
derived from browser-editable `user_metadata`. The Auth `app_metadata` value
`pbhs_display_name` is a server-written display convenience only; it grants no
permission. Existing RLS follows:

`auth.uid() -> department_profiles -> memo_private helpers -> RLS`

Active department members may read resolved Mathematics and FS Mathematics
summaries. Teachers may write only their own papers. Each HOD may additionally
write other staff papers in the HOD's exact subject scope, while retaining
owner-write access for their own papers in the other scope. Unresolved scope
fails closed.

## Password controls

The onboarding UI requires at least 12 characters containing lowercase,
uppercase, a digit, and a symbol before it calls Supabase Auth. Supabase remains
the final password authority. Password-manager use is recommended.

Leaked Password Protection is unavailable on the current Supabase Free plan. It
may be enabled later on a qualifying plan; the app does not claim that this check
is active.

## Dry run and duplicate handling

`--dry-run` validates the input and, when trusted runtime credentials are
available, reads existing Auth/profile state without creating an identity,
invitation, or profile. Without credentials it performs offline validation and
reports that existing state was not checked.

The utility distinguishes new, invite-pending, confirmed, missing-profile,
inactive, mismatched, and conflicting-profile states. It refuses silent account
duplication and requires explicit `--repair-profile`, `--update-profile`, or
`--reissue-invite` intent for the corresponding administrative action. An
expired link is reissued against the existing unconfirmed identity and profile;
it never creates a second profile.

## Secret handling

The trusted utility prefers a modern Supabase `sb_secret_...` key supplied only
as `SUPABASE_SECRET_KEY`. Its deprecated `SUPABASE_SERVICE_ROLE_KEY` fallback is
retained temporarily for the provisioning CLI and is never preferred. The
hosted validation harness requires the modern variable and does not accept the
legacy fallback.

Admin keys, passwords, and action links are runtime-only. The safe JSON result
contains only state and UUID diagnostics. An actual action link is shown once to
the administrator for immediate delivery through official PBHS email. It is not
stored in the database, source tree, documentation, fixtures, or durable test
logs. Hosted automation must keep the link in memory and redact token material.
Structured and text diagnostics redact modern secrets, JWT-shaped legacy keys,
invite tokens, passwords, and authorization/API-key headers before output.

Private JSON/CSV inputs belong outside tracked files; `provisioning-private/` is
ignored as a local convenience. No real staff list belongs in this repository.

## Expiry and reissue

Supabase's configured invite expiry remains unchanged. The Teacher App reports:

> This invitation has expired. Ask the Mathematics Department administrator for
> a new invitation.

The administrator verifies the identity and uses `--reissue-invite`. Expiry must
not be weakened for convenience.

## Stop boundary

Before a reviewed production deployment, production Auth configuration must add
the exact onboarding redirect URL and set the minimum password length to 12 with
the strongest available mixed-character requirement. These are Auth
configuration changes, not a database migration. Validation uses the exact
hosted redirect and rejects weak passwords server-side.

Do not provision real staff, send invitations, backfill production library data,
or expose the Department Library dashboard until Phase 8.3B has been reviewed
and separately approved for rollout.
