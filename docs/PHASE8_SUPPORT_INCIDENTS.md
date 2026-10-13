# Phase 8 teacher support incidents

This pre-release support path lets an authenticated teacher save a small, safe diagnostic snapshot without changing or restarting their memo job. The teacher receives a reference in the form `PBHS-YYYYMMDD-XXXXXXXX` and remains on the same screen.

The incident record and administrator notification are separate. Saving succeeds even when notification is unavailable. Outbound email remains disabled until an administrator approves and configures a provider. The current notification boundary supports Resend through Edge Function secrets `SUPPORT_EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `SUPPORT_EMAIL_FROM`, and `SUPPORT_EMAIL_TO`. These values must never be added to Git or frontend configuration.

## Investigation procedure

Using trusted Supabase tooling, locate `support_incidents.reference`, then inspect only the records needed for the case:

1. Read the incident and its safe snapshot, note, app version, and notification status.
2. Resolve `user_id` through `department_profiles` to identify the teacher.
3. If `job_id` is present, inspect that job's current status and stage, then its `job_events`, active exceptions, and confirmed corrections.
4. Compare `latest_safe_error` with the authoritative job and event data. The incident does not contain memo content.
5. Change the incident status from `open` to `investigating` while working, then to `resolved`; set `resolved_at` and a concise `resolution_note` at closure.

Ordinary teachers can insert and read only their own incidents. They cannot update workflow fields, change ownership, delete incidents, or read another teacher's reports. Trusted service administration may investigate and update records. The v1 procedure intentionally uses trusted Supabase inspection rather than an administrator dashboard.
