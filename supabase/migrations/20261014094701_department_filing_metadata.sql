-- Phase 8 departmental filing metadata for new teacher uploads.
-- Historical jobs remain nullable and continue to use canonical/source metadata.

alter table public.jobs
  add column if not exists filing_contract_version text,
  add column if not exists filing_metadata jsonb,
  add column if not exists display_name text;

alter table public.jobs
  add constraint jobs_filing_contract_version_check
    check (filing_contract_version is null or filing_contract_version = '1.0'),
  add constraint jobs_filing_metadata_object
    check (
      filing_metadata is null
      or (
        jsonb_typeof(filing_metadata) = 'object'
        and filing_metadata ->> 'schema_version' = '1.0'
        and octet_length(filing_metadata::text) <= 4096
      )
    ),
  add constraint jobs_display_name_safe
    check (
      display_name is null
      or (
        length(btrim(display_name)) between 1 and 120
        and display_name = btrim(display_name)
        and display_name !~ '[[:cntrl:]/\\:*?"<>|]'
        and display_name !~ '\.\.'
      )
    );

comment on column public.jobs.filing_contract_version is
  'New-upload filing contract marker. NULL identifies grandfathered historical jobs.';
comment on column public.jobs.filing_metadata is
  'Teacher-supplied administrative filing classification; never source/canonical evidence.';
comment on column public.jobs.display_name is
  'Safe friendly departmental name. source_filename remains immutable source evidence.';

drop policy if exists "jobs_insert_own" on public.jobs;
create policy "jobs_insert_own" on public.jobs
  for insert to authenticated
  with check (
    (select auth.uid()) = user_id
    and status = 'queued'
    and filing_contract_version = '1.0'
  );

alter table public.paper_library_summary
  add column if not exists assessment_number integer,
  add column if not exists duration_value numeric,
  add column if not exists duration_unit text,
  add column if not exists display_name text;

alter table public.paper_library_summary
  add constraint paper_library_assessment_number_check
    check (assessment_number is null or assessment_number between 1 and 4),
  add constraint paper_library_duration_value_check
    check (duration_value is null or duration_value > 0),
  add constraint paper_library_duration_unit_check
    check (duration_unit is null or duration_unit in ('minutes', 'hours', 'periods')),
  add constraint paper_library_display_name_safe
    check (
      display_name is null
      or (
        length(btrim(display_name)) between 1 and 120
        and display_name = btrim(display_name)
        and display_name !~ '[[:cntrl:]/\\:*?"<>|]'
        and display_name !~ '\.\.'
      )
    );

comment on column public.paper_library_summary.assessment_number is
  'Departmental assessment sequence number when applicable.';
comment on column public.paper_library_summary.duration_value is
  'Original teacher-entered filing duration value.';
comment on column public.paper_library_summary.duration_unit is
  'Original filing duration unit; periods are never converted to minutes.';
comment on column public.paper_library_summary.display_name is
  'Friendly departmental title projected from the owning job.';
