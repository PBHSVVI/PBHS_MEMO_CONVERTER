-- PBHS GDE Memo Builder — Phase 0 FK index housekeeping

create index if not exists job_events_user_id_idx
  on public.job_events (user_id);

create index if not exists exceptions_job_id_idx
  on public.exceptions (job_id);
create index if not exists exceptions_user_id_idx
  on public.exceptions (user_id);
create index if not exists exceptions_resolved_by_correction_idx
  on public.exceptions (resolved_by_correction_id);

create index if not exists corrections_job_id_idx
  on public.corrections (job_id);
create index if not exists corrections_user_id_idx
  on public.corrections (user_id);
create index if not exists corrections_exception_id_idx
  on public.corrections (exception_id);
