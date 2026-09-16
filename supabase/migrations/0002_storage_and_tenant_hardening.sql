-- PBHS GDE Memo Builder — Phase 0 private storage and tenant integrity

insert into storage.buckets (id, name, public)
values ('memo-files', 'memo-files', false)
on conflict (id) do update set public = excluded.public;

create policy "memo_files_select_own"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
);

create policy "memo_files_insert_own_inputs"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
);

create policy "memo_files_update_own_inputs"
on storage.objects
for update
to authenticated
using (
  bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
)
with check (
  bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
);

create policy "memo_files_delete_own_inputs"
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'memo-files'
  and split_part(name, '/', 1) = (select auth.uid())::text
  and split_part(name, '/', 3) in ('source', 'corrections')
);

drop policy if exists "corrections_insert_own" on public.corrections;

create policy "corrections_insert_own"
on public.corrections
for insert
to authenticated
with check (
  (select auth.uid()) = user_id
  and exists (
    select 1
    from public.jobs j
    where j.id = job_id
      and j.user_id = (select auth.uid())
  )
  and (
    exception_id is null
    or exists (
      select 1
      from public.exceptions e
      where e.id = exception_id
        and e.job_id = job_id
        and e.user_id = (select auth.uid())
    )
  )
);
