-- Phase 8 Priority 2: small, durable teacher support incidents.

create table if not exists public.support_incidents (
  id uuid primary key default gen_random_uuid(),
  reference text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete restrict,
  job_id uuid references public.jobs(id) on delete set null,
  incident_type text not null check (incident_type in ('stuck', 'looks_wrong', 'error', 'other')),
  teacher_note text check (
    teacher_note is null or (
      length(teacher_note) <= 1200
      and teacher_note !~* '(sb_secret_|sb_publishable_|bearer[[:space:]]+|authorization|access[_ -]?token|refresh[_ -]?token|api[_ -]?key|password|token_hash=|/auth/v1/verify)'
    )
  ),
  current_view text check (current_view is null or length(current_view) <= 80),
  current_stage text check (current_stage is null or length(current_stage) <= 120),
  job_status text check (job_status is null or length(job_status) <= 80),
  review_required boolean,
  question_context text check (question_context is null or length(question_context) <= 120),
  latest_safe_error text check (
    latest_safe_error is null or (
      length(latest_safe_error) <= 160
      and latest_safe_error !~* '(sb_secret_|sb_publishable_|bearer[[:space:]]+|authorization|access[_ -]?token|refresh[_ -]?token|api[_ -]?key|password|token_hash=|/auth/v1/verify)'
    )
  ),
  unresolved_exception_count integer check (unresolved_exception_count is null or unresolved_exception_count >= 0),
  app_version text check (app_version is null or length(app_version) <= 120),
  user_agent_summary text check (user_agent_summary is null or length(user_agent_summary) <= 120),
  viewport_class text check (viewport_class is null or viewport_class in ('phone', 'tablet', 'desktop')),
  status text not null default 'open' check (status in ('open', 'investigating', 'resolved')),
  notification_status text not null default 'pending' check (notification_status in ('pending', 'sent', 'failed', 'unavailable')),
  notification_last_error text check (notification_last_error is null or length(notification_last_error) <= 160),
  resolved_at timestamptz,
  resolution_note text check (resolution_note is null or length(resolution_note) <= 2000)
);

create index if not exists support_incidents_user_created_idx
  on public.support_incidents (user_id, created_at desc);
create index if not exists support_incidents_status_created_idx
  on public.support_incidents (status, created_at desc);
create index if not exists support_incidents_job_idx
  on public.support_incidents (job_id) where job_id is not null;

create or replace function memo_private.phase8_support_incident_stamp()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    new.user_id := (select auth.uid());
    new.reference := 'PBHS-' || to_char(now() at time zone 'Africa/Johannesburg', 'YYYYMMDD') || '-' || upper(substr(replace(new.id::text, '-', ''), 1, 8));
    new.status := 'open';
    new.notification_status := 'pending';
    new.notification_last_error := null;
    new.resolved_at := null;
    new.resolution_note := null;
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists support_incidents_stamp on public.support_incidents;
create trigger support_incidents_stamp
before insert or update on public.support_incidents
for each row execute function memo_private.phase8_support_incident_stamp();

alter table public.support_incidents enable row level security;

drop policy if exists "support_incidents_insert_own" on public.support_incidents;
create policy "support_incidents_insert_own"
on public.support_incidents
for insert
to authenticated
with check (
  (select auth.uid()) = user_id
  and (job_id is null or exists (
    select 1 from public.jobs j
    where j.id = job_id and j.user_id = (select auth.uid())
  ))
);

drop policy if exists "support_incidents_select_own" on public.support_incidents;
create policy "support_incidents_select_own"
on public.support_incidents
for select
to authenticated
using ((select auth.uid()) = user_id);

revoke all on public.support_incidents from public, anon, authenticated, service_role;
grant select, insert on public.support_incidents to authenticated;
grant select, insert, update on public.support_incidents to service_role;

revoke all on function memo_private.phase8_support_incident_stamp() from public, anon, authenticated;

comment on table public.support_incidents is
  'Teacher-owned safe support snapshots. Memo content, credentials and session material are prohibited.';
