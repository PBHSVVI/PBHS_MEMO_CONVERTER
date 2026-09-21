-- PBHS GDE Memo Builder — Phase 7.1 correction overlay + rerun reconciliation

alter table public.corrections
  add column if not exists applied_at timestamptz;

alter table public.exceptions
  drop constraint if exists exceptions_status_check;

alter table public.exceptions
  add constraint exceptions_status_check check (
    status in (
      'open',
      'awaiting_reinterpretation',
      'awaiting_confirmation',
      'resolved',
      'superseded'
    )
  );

create index if not exists exceptions_job_status_idx
on public.exceptions (job_id, status);
