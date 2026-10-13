# Phase 8.3B — Secure Staff Onboarding Foundation

Status: scanner-safe code onboarding remains implemented locally. The temporary
first-login-password fallback has also passed synthetic hosted validation on
`wgkydsildfmbqzvicuwm`; its migration and JWT-protected completion function are
deployed only there. Full hosted email delivery remains blocked until Custom
SMTP is available. The frontend and provisioning utility have not been pushed,
and neither fallback code nor schema has been deployed to production. No real PBHS staff were provisioned.

The validation project passed the native Auth lifecycle through a temporary,
removed test harness: harmless scanner GETs, invalid/replayed OTP denial,
single-use OTP verification, active/missing/inactive profile decisions, password
policy enforcement, forced sign-out, normal password login, unprovisioned-user
denial, and recovery of an existing unconfirmed invite-era identity. Synthetic
identities and profiles were deleted after the run.

## Temporary Friday first-login fallback

While production Custom SMTP is awaiting approval, a local-only fallback allows
a trusted administrator to provision one explicitly named staff member with a
runtime staff code as a temporary Auth password. This does not replace the
scanner-safe OTP architecture described below. The fallback is intended to be
retired for new users once production code delivery is available.

`department_profiles.must_change_password` is the server-controlled state for
this path. A temporary-password profile starts with the flag set. After sign-in,
the Teacher App shows only **Choose your private password**. Normal job,
correction, support, storage, and department-library RLS requires an active
profile whose flag is clear.

The JWT-protected `complete-first-login` function validates the caller and the
server-side profile state, applies the new password through the caller's Auth
session, then invokes a service-only completion RPC for that same Auth UUID. The
browser cannot call the completion RPC, update a profile, select another user,
or change role, HOD scope, or active state. The app signs the teacher out after
completion and requires a normal login with the replacement password.

Trusted provisioning enables the fallback only with `--temporary-password` and
a runtime `staff_code` input. Safe output records only
`temporary_password_supplied: true`; it never contains the value. Private staff
JSON or CSV input belongs under the Git-ignored `provisioning-private/`
directory and contains these columns:

`display_name,email,role,hod_scope,staff_code`

Supply exactly one staff record per invocation. Do not place real values in
source, documentation, shell history, screenshots, or generated reports. The
same explicit mode can preserve an existing matching Auth identity and profile
while setting a new temporary password and the first-login flag. It refuses
identity/profile mismatches and does not alter role, HOD scope, or active state.

## Scanner-safe architecture

Staff onboarding remains administrator-provisioned. A trusted administrator runs
`web/scripts/provision-staff.mjs` with staff identity, application role, and any
HOD subject scope supplied at runtime. The utility uses the Supabase Admin API to
create a confirmed Auth identity with no password and no consumable invite URL.
Once it has the Auth UUID, it creates the matching `department_profiles` row
through the trusted secret-key client.

The administrator gives staff this permanent page:

`https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/?onboarding=setup`

The page contains no token. The teacher enters their email, and the app calls
`signInWithOtp` with `shouldCreateUser: false`. The Magic Link Auth template must
contain `{{ .Token }}` and must not contain `{{ .ConfirmationURL }}` or
`{{ .TokenHash }}`. The teacher enters the code, the app verifies it with
`verifyOtp({ email, token, type: "email" })`, and a boolean-only RPC confirms an
active department profile. The teacher can then set a password. The app signs
the setup session out before returning to normal password sign-in.

Email security scanners can GET the permanent setup URL repeatedly without
touching Auth state. No consumable Auth credential appears in the URL or email
link. Only manual code submission reaches the OTP verification endpoint.

Supabase email OTP is technically available to every existing email-provider
identity, including a staff member who already has a password. The normal Sign
In screen does not expose passwordless login, but possession of the staff
mailbox plus the permanent setup page can establish a session and replace that
account's password. This is the intended recovery model for the pilot and should
be reviewed alongside PBHS mailbox security before the wider rollout.

## Authorization boundary

`department_profiles` remains the application authorization source of truth.
The browser cannot read or change it. Role, HOD scope, and active state are never
derived from browser-editable `user_metadata`. The Auth `app_metadata` value
`pbhs_display_name` is a server-written display convenience only; it grants no
permission. Existing RLS follows:

`auth.uid() -> department_profiles -> memo_private helpers -> RLS`

The onboarding RPC returns only a boolean active-membership fact. It does not
expose profile rows, role, scope, or other staff data.

## Password and OTP controls

The onboarding UI requires at least 12 characters containing lowercase,
uppercase, a digit, and a symbol before it calls Supabase Auth. Supabase remains
the final password authority. Password-manager use is recommended.

OTP expiry and resend throttling remain Supabase Auth policy. The setup screen
reports invalid, expired, and used codes with one safe message and lets the
teacher request a new code. The validation baseline observed before the blocked
template update was an eight-digit code, one-hour expiry, one-minute resend
frequency, and 30 verification attempts per five minutes. Production values must
be reviewed before rollout and must not be weakened for convenience.

Leaked Password Protection is unavailable on the current Supabase Free plan. It
may be enabled later on a qualifying plan; the app does not claim that this check
is active.

## Dry run and duplicate handling

`--dry-run` validates the input and, when trusted runtime credentials are
available, reads existing Auth/profile state without creating an identity or
profile. Without credentials it performs offline validation and reports that
existing state was not checked.

The utility distinguishes new, setup-pending, confirmed, missing-profile,
inactive, mismatched, and conflicting-profile states. It refuses silent account
duplication and requires explicit `--repair-profile` or `--update-profile` intent
for those administrative actions. Raw invite reissue is refused. Staff receive
the same permanent setup URL and request a fresh code from Auth.

## Secret handling

The trusted utility prefers a modern Supabase `sb_secret_...` key supplied only
as `SUPABASE_SECRET_KEY`. Its deprecated `SUPABASE_SERVICE_ROLE_KEY` fallback is
retained temporarily for the provisioning CLI and is never preferred. Hosted
validation requires modern publishable and secret credentials.

Admin keys, OTPs, passwords, and any historical action links are runtime-only.
Safe reports redact modern secrets, JWT-shaped legacy keys, invite tokens,
passwords, and authorization/API-key headers. Private JSON/CSV inputs belong in
the ignored `provisioning-private/` directory.

## Historical invite-link implementation

Phase 8.3B originally generated one-time Supabase invite action links. That
implementation was correctly validated for identity/profile idempotency and RLS,
but institutional link scanning consumed Amanda's link before she opened it.
The scanner-safe change preserves those provisioning and authorization lessons
while replacing link delivery. Historical records and commits remain valid
evidence of the earlier implementation; they are not rewritten as though
code-based onboarding existed from the beginning.

## Hosted Auth configuration

For each approved project, an administrator must:

1. Configure Custom SMTP. Resend is recommended for the wider rollout; use a
   verified PBHS-controlled sending domain rather than `onboarding@resend.dev`.
2. In **Authentication → Email Templates → Magic Link**, copy
   `supabase/templates/pbhs_setup_otp.html`. Confirm that the template contains
   `{{ .Token }}` and contains no `ConfirmationURL` or `TokenHash`.
3. Set the Site URL to the Teacher App base URL and allow the permanent
   `?onboarding=setup` URL.
4. Disable project-wide public signup. Keep the email provider enabled so
   existing users can use OTP and password login; the app additionally sends
   `shouldCreateUser: false`.
5. Keep minimum password length 12 with lowercase, uppercase, digits, and
   symbols.
6. Review OTP expiry, code length, email frequency, and verification rate limits.

Default Supabase Auth mail is not sufficient for this Free-plan rollout because
that plan/provider combination does not allow the required code-only template.

## Stop boundary

Do not change production Auth configuration, deploy the frontend, send Amanda an
OTP, alter her identity/profile, provision other staff, or begin the wider staff
rollout without a separate reviewed production approval.
