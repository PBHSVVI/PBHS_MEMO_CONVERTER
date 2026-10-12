# Phase 8.3A — Department Library Authorization Foundation

Status: local implementation candidate. The migration has not been applied and
the worker change has not been deployed.

## Architecture

`department_profiles` stores the application role, HOD subject scope, active
state, and safe display label for a Supabase Auth user. It stores no password or
temporary credential. Ordinary clients cannot select this table.

`paper_library_summary` stores one worker-maintained row per job. Its metadata is
built from `canonical.document_metadata`, after the accepted source-first,
teacher-fallback resolution. Null metadata remains null. A strict mapping turns
only resolved `MATHEMATICS` and `FS MATHEMATICS` subjects into the stable scopes
`mathematics` and `fs_mathematics`; any other or unresolved subject remains null
and is excluded by RLS.

Active department users may read summary rows in either supported subject scope.
Unauthenticated, inactive, and non-department users cannot read the library.
`owner_user_id = auth.uid()` supports the later **My papers** filter over the same
authorized result set.

## Write authorization primitive

`memo_private.can_write_paper(job_id)` is a non-exposed security-definer function that returns true only
when the caller has an active department profile and either owns the job, or is
an HOD whose exact `hod_scope` matches the resolved summary subject scope. An
unresolved subject therefore never grants subject-wide HOD write access. This
function is the basis for a later Phase 8.3B policy update. Its search path is
empty, every relation is schema-qualified, and execution is revoked from PUBLIC
and anonymous callers. This migration does
not broaden correction, exception, job, metadata, or Storage write policies.

## Worker population

The hosted worker upserts the summary after canonical metadata is available. It
publishes an in-progress row before review/rendering and refreshes it after a
needs-review or complete transition. Reprocessing the same job updates its single
primary-key row rather than creating a duplicate. Existing technical job status,
stage, and `completed_at` remain the lifecycle source of truth.

## Trusted backend privileges

Migration `0007` revokes platform-default access from `PUBLIC`, `anon`,
`authenticated`, and `service_role` before granting back the required
operations. Trusted profile administration receives `SELECT`, `INSERT`, and
`UPDATE` on `department_profiles`; profiles are deactivated rather than deleted.
The worker receives `SELECT`, `INSERT`, and `UPDATE` on
`paper_library_summary` for verified conflict upserts. It receives no `DELETE`,
`TRUNCATE`, `REFERENCES`, or `TRIGGER` privilege on either table. Authenticated
browser clients receive only `SELECT` on the summary table, subject to RLS, and
no direct profile-table access.

## Shared downloads

Private Storage remains owner-scoped. A blanket authenticated object-read policy
would expose unrelated private objects and is not acceptable. The recommended
next increment is an authenticated signed-download Edge endpoint that calls a
dedicated `can_read_paper` helper, validates an allowlisted
output path, and returns a short-lived URL. Existing owner downloads remain
unchanged.

## Rollout order

Apply and verify migration `0007_phase83a_department_library.sql` before deploying
worker code that writes the summary. Provision real department profiles only in a
separate explicitly approved step. After hosted RLS and worker-population tests,
the frontend departmental library can consume `paper_library_summary` directly.

Before any real PBHS staff account is provisioned, production Supabase Auth must
have Leaked Password Protection enabled. The approved first-login lifecycle is a
temporary staff-code password followed by a forced password change, after which
the temporary password is no longer usable. Staff codes and temporary passwords
must never be stored in migrations, source files, tests, logs, or documentation.

## Migration safety and remediation

The migration creates new tables, indexes, triggers, and functions. It does not
drop or alter accepted job, correction, exception, event, or Storage objects and
does not replace their policies. Reapplying the complete migration is intended
to be safe: tables and indexes use `if not exists`, functions use `create or
replace`, and the new triggers and summary policy are dropped and recreated by
name. This does not attempt to repair a partially hand-edited schema; a failed
application must be inspected before retrying.

Before any production rollout, take a schema-only backup and verify the migration
on an isolated branch. If remediation is required before profiles or summaries
are populated, remove the new policy and triggers, then drop the two new tables
and the dedicated `memo_private` schema. After data exists, preserve/export the
summary and profile rows before reversing anything. Worker deployment must follow
the migration; rolling worker code back first prevents new summary writes while
leaving the additive tables harmlessly in place.
