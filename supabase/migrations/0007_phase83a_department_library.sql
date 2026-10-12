-- Phase 8.3A: server-enforced departmental library and authorization foundation.

create schema if not exists memo_private;
revoke all on schema memo_private from public, anon;
grant usage on schema memo_private to authenticated;

create table if not exists public.department_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (length(btrim(display_name)) between 1 and 120),
  email text not null check (length(btrim(email)) between 3 and 320),
  role text not null check (role in ('teacher', 'hod')),
  hod_scope text check (hod_scope in ('mathematics', 'fs_mathematics')),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint department_profiles_role_scope_check check (
    (role = 'teacher' and hod_scope is null)
    or (role = 'hod' and hod_scope is not null)
  )
);

create table if not exists public.paper_library_summary (
  job_id uuid primary key references public.jobs(id) on delete cascade,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  owner_display_name text,
  subject_scope text check (subject_scope in ('mathematics', 'fs_mathematics')),
  subject_display text,
  assessment_type text,
  year integer,
  paper text,
  grade_label text,
  duration_minutes integer,
  expected_total_marks integer,
  computed_total_marks integer,
  term text,
  source_filename text,
  workflow_bucket text not null check (workflow_bucket in ('in_progress', 'completed')),
  status_source text not null,
  stage_source text,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  completed_at timestamptz,
  summary_updated_at timestamptz not null default now()
);

create index if not exists paper_library_summary_filter_idx
  on public.paper_library_summary
    (subject_scope, workflow_bucket, grade_label, updated_at desc);
create index if not exists paper_library_summary_owner_idx
  on public.paper_library_summary (owner_user_id, updated_at desc);

create or replace function memo_private.phase83a_profile_stamp()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  new.display_name := btrim(new.display_name);
  new.email := lower(btrim(new.email));
  new.updated_at := now();
  return new;
end;
$$;

create or replace function memo_private.phase83a_summary_stamp()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  select j.user_id
    into new.owner_user_id
    from public.jobs j
   where j.id = new.job_id;
  select p.display_name
    into new.owner_display_name
    from public.department_profiles p
   where p.user_id = new.owner_user_id;
  new.summary_updated_at := now();
  return new;
end;
$$;

create or replace function memo_private.phase83a_refresh_owner_label()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.paper_library_summary
     set owner_display_name = new.display_name,
         summary_updated_at = now()
   where owner_user_id = new.user_id;
  return new;
end;
$$;

drop trigger if exists department_profiles_stamp on public.department_profiles;
create trigger department_profiles_stamp
before insert or update on public.department_profiles
for each row execute function memo_private.phase83a_profile_stamp();

drop trigger if exists paper_library_summary_stamp on public.paper_library_summary;
create trigger paper_library_summary_stamp
before insert or update on public.paper_library_summary
for each row execute function memo_private.phase83a_summary_stamp();

drop trigger if exists department_profiles_refresh_owner_label on public.department_profiles;
create trigger department_profiles_refresh_owner_label
after insert or update of display_name on public.department_profiles
for each row execute function memo_private.phase83a_refresh_owner_label();

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

alter table public.department_profiles enable row level security;
alter table public.paper_library_summary enable row level security;

drop policy if exists "department_library_read_active_staff" on public.paper_library_summary;
create policy "department_library_read_active_staff"
on public.paper_library_summary
for select
to authenticated
using (
  (select memo_private.is_active_department_member())
  and subject_scope in ('mathematics', 'fs_mathematics')
);

-- Supabase may provision broad platform-default grants on new public tables.
-- Establish this boundary explicitly before granting back the operations used by
-- trusted profile administration and the worker's idempotent summary upsert.
revoke all on public.department_profiles
  from public, anon, authenticated, service_role;
revoke all on public.paper_library_summary
  from public, anon, authenticated, service_role;

grant select, insert, update on public.department_profiles to service_role;
grant select on public.paper_library_summary to authenticated;
grant select, insert, update on public.paper_library_summary to service_role;

revoke all on function memo_private.phase83a_profile_stamp() from public, anon, authenticated;
revoke all on function memo_private.phase83a_summary_stamp() from public, anon, authenticated;
revoke all on function memo_private.phase83a_refresh_owner_label() from public, anon, authenticated;
revoke all on function memo_private.is_active_department_member() from public, anon;
revoke all on function memo_private.can_write_paper(uuid) from public, anon;
grant execute on function memo_private.is_active_department_member() to authenticated;
grant execute on function memo_private.can_write_paper(uuid) to authenticated;

comment on table public.department_profiles is
  'Safe departmental application profile. Authentication credentials remain in Supabase Auth.';
comment on table public.paper_library_summary is
  'Worker-maintained effective memo metadata for the authorized departmental library.';
comment on function memo_private.can_write_paper(uuid) is
  'Server-side authorization primitive: active owners write their papers; HODs also write papers in their exact subject scope.';
