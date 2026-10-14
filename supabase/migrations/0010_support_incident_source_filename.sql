-- Preserve the safe source filename in teacher support context without storing
-- memo contents or browser/session credentials.

alter table public.support_incidents
  add column if not exists source_filename text
  check (source_filename is null or length(source_filename) <= 260);

comment on column public.support_incidents.source_filename is
  'Sanitized source filename captured for support triage; memo contents are excluded.';
