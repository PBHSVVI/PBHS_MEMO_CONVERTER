-- Phase 8.1B: bounded teacher-supplied document metadata fallback.

alter table public.jobs
  add column if not exists teacher_metadata jsonb not null
    default '{"schema_version":"1.0","values":{},"confirmed_absent":[]}'::jsonb,
  add column if not exists teacher_metadata_revision integer not null default 0,
  add column if not exists teacher_metadata_updated_at timestamptz;

alter table public.jobs
  add constraint jobs_teacher_metadata_revision_nonnegative
    check (teacher_metadata_revision >= 0),
  add constraint jobs_teacher_metadata_object
    check (
      jsonb_typeof(teacher_metadata) = 'object'
      and jsonb_typeof(teacher_metadata -> 'values') = 'object'
      and jsonb_typeof(teacher_metadata -> 'confirmed_absent') = 'array'
      and teacher_metadata ->> 'schema_version' = '1.0'
      and octet_length(teacher_metadata::text) <= 4096
    );

comment on column public.jobs.teacher_metadata is
  'Validated teacher fallback document metadata. Explicit source metadata always wins.';
comment on column public.jobs.teacher_metadata_revision is
  'Monotonic revision of accepted teacher metadata submissions.';
