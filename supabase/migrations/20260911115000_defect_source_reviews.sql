create table if not exists public.defect_source_reviews (
  id uuid primary key default gen_random_uuid(),
  source_url text not null unique,
  make text not null,
  model text not null,
  year integer,
  engine text not null default '',
  title text not null,
  snippet text not null default '',
  source_name text not null,
  source_type text not null,
  status text not null default 'pending_review',
  reviewed_at timestamptz,
  reviewed_by text not null default 'developer',
  created_at timestamptz not null default now(),
  constraint defect_source_reviews_year_check
    check (year is null or (year between 1886 and 2100)),
  constraint defect_source_reviews_status_check
    check (status in ('pending_review', 'published', 'rejected')),
  constraint defect_source_reviews_source_type_check
    check (source_type in ('official_candidate', 'manufacturer_candidate', 'community_candidate', 'independent_candidate'))
);

alter table public.defect_source_reviews enable row level security;
revoke all on table public.defect_source_reviews from anon, authenticated;

create policy defect_source_reviews_no_client_access
  on public.defect_source_reviews
  for all to anon, authenticated
  using (false)
  with check (false);
