-- PBHS GDE Memo Builder — Phase 0 core schema

create extension if not exists pgcrypto;

create table if not exists public.jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  status text not null default 'queued',
  stage text not null default 'upload',
  source_filename text,
  source_mime text,
  source_path text,
  source_sha256 text,
  source_size_bytes bigint,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  review_required boolean not null default false,
  document_schema_version text not null default '1.0',
  render_profile text not null default 'PBHS_GDE_INTERNAL_V1',
  engine_version text,
  github_run_id bigint,
  error_code text,
  error_message text,
  dispatched_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint jobs_status_check check (
    status in (
      'created','queued','dispatched','processing','needs_review',
      'correction_pending','correction_confirmed','rendering',
      'complete','failed_retryable','failed'
    )
  )
);

create index if not exists jobs_user_created_idx on public.jobs (user_id, created_at desc);
create index if not exists jobs_status_idx on public.jobs (status);

create table if not exists public.job_events (
  id bigint generated always as identity primary key,
  job_id uuid not null references public.jobs(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  event_type text not null,
  stage text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists job_events_job_created_idx on public.job_events (job_id, created_at);

create table if not exists public.exceptions (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  level text not null check (level in ('amber', 'red')),
  category text not null,
  affected_id text,
  message text not null,
  suggestions jsonb not null default '[]'::jsonb,
  status text not null default 'open'
    check (status in ('open','awaiting_reinterpretation','awaiting_confirmation','resolved')),
  resolved_by_correction_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.corrections (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  exception_id uuid references public.exceptions(id) on delete set null,
  input_kind text not null check (input_kind in ('suggestion','typed','photo','upload')),
  typed_text text,
  storage_path text,
  display_text text,
  proposed_patch jsonb,
  confirmation_status text not null default 'pending'
    check (confirmation_status in ('pending','confirmed','rejected')),
  created_at timestamptz not null default now(),
  confirmed_at timestamptz
);

alter table public.exceptions
  add constraint exceptions_resolved_by_correction_fk
  foreign key (resolved_by_correction_id)
  references public.corrections(id)
  on delete set null;

alter table public.jobs enable row level security;
alter table public.job_events enable row level security;
alter table public.exceptions enable row level security;
alter table public.corrections enable row level security;

create policy "jobs_select_own" on public.jobs
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "jobs_insert_own" on public.jobs
  for insert to authenticated
  with check ((select auth.uid()) = user_id and status = 'queued');

create policy "job_events_select_own" on public.job_events
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "exceptions_select_own" on public.exceptions
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "corrections_select_own" on public.corrections
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "corrections_insert_own" on public.corrections
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

revoke all on public.jobs from anon;
revoke all on public.job_events from anon;
revoke all on public.exceptions from anon;
revoke all on public.corrections from anon;

grant select, insert on public.jobs to authenticated;
grant select on public.job_events to authenticated;
grant select on public.exceptions to authenticated;
grant select, insert on public.corrections to authenticated;

-- No client UPDATE policy for jobs: worker/dispatch transitions are server-controlled.
-- Storage bucket/policies are added only after a dedicated Supabase project exists,
-- so current Storage APIs/policy behaviour can be verified before deployment.
