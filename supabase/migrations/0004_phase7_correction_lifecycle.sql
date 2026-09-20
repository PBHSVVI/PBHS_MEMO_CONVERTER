-- PBHS GDE Memo Builder — Phase 7.0 correction lifecycle hardening

alter table public.corrections
  add column if not exists updated_at timestamptz not null default now();

drop policy if exists "corrections_insert_own" on public.corrections;

create policy "corrections_insert_own"
on public.corrections
for insert
to authenticated
with check (
  (select auth.uid()) = user_id
  and confirmation_status = 'pending'
  and proposed_patch is null
  and exists (
    select 1
    from public.jobs j
    where j.id = job_id
      and j.user_id = (select auth.uid())
      and j.status in ('needs_review','correction_pending')
  )
  and exception_id is not null
  and exists (
    select 1
    from public.exceptions e
    where e.id = exception_id
      and e.job_id = corrections.job_id
      and e.user_id = (select auth.uid())
      and e.status in ('open','awaiting_reinterpretation','awaiting_confirmation')
  )
);

-- Confirmation/rejection is server-controlled. Browser users may never mutate
-- proposed patches, exception state or job state directly.
revoke update on public.corrections from authenticated;
revoke update on public.exceptions from authenticated;
revoke update on public.jobs from authenticated;

create unique index if not exists corrections_one_pending_per_exception_idx
on public.corrections (exception_id)
where confirmation_status = 'pending' and exception_id is not null;

create index if not exists corrections_job_created_idx
on public.corrections (job_id, created_at desc);

create index if not exists corrections_exception_created_idx
on public.corrections (exception_id, created_at desc);
