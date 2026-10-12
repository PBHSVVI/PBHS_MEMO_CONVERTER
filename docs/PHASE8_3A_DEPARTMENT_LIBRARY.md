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

`private.can_write_paper(job_id)` is a non-exposed security-definer function that returns true only
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
