alter table public.trial_entitlements
  add column if not exists device_hash text;

do $$
begin
  alter table public.trial_entitlements
    add constraint trial_entitlements_device_hash_format
    check (
      device_hash is null
      or device_hash ~ '^[0-9a-f]{64}$'
    );
exception
  when duplicate_object then null;
end
$$;

create unique index if not exists trial_entitlements_device_hash_unique
  on public.trial_entitlements (device_hash)
  where device_hash is not null;

alter table public.trial_entitlements enable row level security;

revoke all on table public.trial_entitlements from anon, authenticated;
grant select, insert, update, delete
  on table public.trial_entitlements to service_role;

comment on column public.trial_entitlements.device_hash is
  'SHA-256 app-scoped Android device identifier; prevents repeated trials across accounts.';
