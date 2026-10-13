-- Phase 8.4: expose only the boolean membership fact needed after OTP
-- verification. Department role and scope remain private and authoritative.
create or replace function public.pbhs_active_profile_status()
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

revoke all on function public.pbhs_active_profile_status() from public, anon;
grant execute on function public.pbhs_active_profile_status() to authenticated;

comment on function public.pbhs_active_profile_status() is
  'Returns only whether the authenticated user has an active PBHS department profile; role and scope remain private.';
