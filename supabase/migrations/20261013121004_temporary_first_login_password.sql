-- Temporary Friday onboarding fallback: a trusted administrator may assign a
-- one-time password, but ordinary application access remains blocked until the
-- authenticated teacher replaces it. Scanner-safe OTP onboarding remains the
-- preferred long-term path.

alter table public.department_profiles
  add column if not exists must_change_password boolean not null default false;

create or replace function memo_private.is_active_department_member()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.department_profiles p
     where p.user_id = (select auth.uid())
       and p.active
       and not p.must_change_password
  );
$$;

create or replace function memo_private.can_write_paper(p_job_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.department_profiles p
      join public.jobs j on j.id = p_job_id
      left join public.paper_library_summary s on s.job_id = j.id
     where p.user_id = (select auth.uid())
       and p.active
       and not p.must_change_password
       and (
         j.user_id = (select auth.uid())
         or (
           p.role = 'hod'
           and p.hod_scope is not null
           and p.hod_scope = s.subject_scope
         )
       )
  );
$$;

-- The browser receives only the gate state. It cannot read the profile row or
-- its authorization attributes.
create or replace function public.pbhs_first_login_status()
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select case
    when not exists (
      select 1 from public.department_profiles p
       where p.user_id = (select auth.uid()) and p.active
    ) then 'unavailable'
    when exists (
      select 1 from public.department_profiles p
       where p.user_id = (select auth.uid())
         and p.active
         and p.must_change_password
    ) then 'password_change_required'
    else 'ready'
  end;
$$;

-- This is intentionally unavailable to browser roles. The JWT-protected
-- complete-first-login Edge Function invokes it with its trusted service client
-- only after the caller's Auth password update succeeds.
create or replace function public.pbhs_complete_initial_password_change(p_user_id uuid)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  changed integer;
begin
  update public.department_profiles
     set must_change_password = false
   where user_id = p_user_id
     and active
     and must_change_password;
  get diagnostics changed = row_count;
  return changed = 1;
end;
$$;

-- Re-establish every normal browser data policy with the completed-onboarding
-- predicate. This provides the backend gate even if frontend routing is
-- bypassed.
drop policy if exists "jobs_select_own" on public.jobs;
create policy "jobs_select_own" on public.jobs
  for select to authenticated
  using (
    (select memo_private.is_active_department_member())
    and (select auth.uid()) = user_id
  );

drop policy if exists "jobs_insert_own" on public.jobs;
create policy "jobs_insert_own" on public.jobs
  for insert to authenticated
  with check (
    (select memo_private.is_active_department_member())
    and (select auth.uid()) = user_id
    and status = 'queued'
  );

drop policy if exists "job_events_select_own" on public.job_events;
create policy "job_events_select_own" on public.job_events
  for select to authenticated
  using (
    (select memo_private.is_active_department_member())
    and (select auth.uid()) = user_id
  );

drop policy if exists "exceptions_select_own" on public.exceptions;
create policy "exceptions_select_own" on public.exceptions
  for select to authenticated
  using (
    (select memo_private.is_active_department_member())
    and (select auth.uid()) = user_id
  );

drop policy if exists "corrections_select_own" on public.corrections;
create policy "corrections_select_own" on public.corrections
  for select to authenticated
  using (
    (select memo_private.is_active_department_member())
    and (select auth.uid()) = user_id
  );

drop policy if exists "corrections_insert_own" on public.corrections;
create policy "corrections_insert_own" on public.corrections
for insert to authenticated
with check (
  (select memo_private.is_active_department_member())
  and (select auth.uid()) = user_id
  and confirmation_status = 'pending'
  and proposed_patch is null
  and exists (
    select 1 from public.jobs j
     where j.id = job_id
       and j.user_id = (select auth.uid())
       and j.status in ('needs_review','correction_pending')
  )
  and exception_id is not null
  and exists (
    select 1 from public.exceptions e
     where e.id = exception_id
       and e.job_id = corrections.job_id
       and e.user_id = (select auth.uid())
       and e.status in ('open','awaiting_reinterpretation','awaiting_confirmation')
  )
);

drop policy if exists "memo_files_select_own" on storage.objects;
create policy "memo_files_select_own" on storage.objects
for select to authenticated
using (
  (select memo_private.is_active_department_member())
  and bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
);

drop policy if exists "memo_files_insert_own_inputs" on storage.objects;
create policy "memo_files_insert_own_inputs" on storage.objects
for insert to authenticated
with check (
  (select memo_private.is_active_department_member())
  and bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
);

drop policy if exists "memo_files_update_own_inputs" on storage.objects;
create policy "memo_files_update_own_inputs" on storage.objects
for update to authenticated
using (
  (select memo_private.is_active_department_member())
  and bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
)
with check (
  (select memo_private.is_active_department_member())
  and bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
);

drop policy if exists "memo_files_delete_own_inputs" on storage.objects;
create policy "memo_files_delete_own_inputs" on storage.objects
for delete to authenticated
using (
  (select memo_private.is_active_department_member())
  and bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
);

drop policy if exists "support_incidents_insert_own" on public.support_incidents;
create policy "support_incidents_insert_own" on public.support_incidents
for insert to authenticated
with check (
  (select memo_private.is_active_department_member())
  and (select auth.uid()) = user_id
  and (job_id is null or exists (
    select 1 from public.jobs j
     where j.id = job_id and j.user_id = (select auth.uid())
  ))
);

drop policy if exists "support_incidents_select_own" on public.support_incidents;
create policy "support_incidents_select_own" on public.support_incidents
for select to authenticated
using (
  (select memo_private.is_active_department_member())
  and (select auth.uid()) = user_id
);

revoke all on function public.pbhs_first_login_status() from public, anon;
grant execute on function public.pbhs_first_login_status() to authenticated;

revoke all on function public.pbhs_complete_initial_password_change(uuid)
  from public, anon, authenticated;
grant execute on function public.pbhs_complete_initial_password_change(uuid)
  to service_role;

comment on column public.department_profiles.must_change_password is
  'Server-controlled first-login gate for temporary-password onboarding; never derived from user_metadata.';
comment on function public.pbhs_first_login_status() is
  'Returns only ready, password_change_required, or unavailable for the authenticated caller.';
comment on function public.pbhs_complete_initial_password_change(uuid) is
  'Trusted completion primitive called only after a successful Auth password update.';
