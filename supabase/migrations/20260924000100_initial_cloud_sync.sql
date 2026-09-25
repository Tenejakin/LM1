create table if not exists public.shots (
  user_id uuid not null references auth.users(id) on delete cascade,
  id text not null,
  data jsonb not null,
  created_at timestamptz not null default now(),
  primary key (user_id, id)
);

create table if not exists public.putts (
  user_id uuid not null references auth.users(id) on delete cascade,
  id text not null,
  data jsonb not null,
  created_at timestamptz not null default now(),
  primary key (user_id, id)
);

create table if not exists public.preferences (
  user_id uuid not null references auth.users(id) on delete cascade,
  key text not null,
  value text not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, key)
);

alter table public.shots enable row level security;
alter table public.putts enable row level security;
alter table public.preferences enable row level security;

create policy "Users manage their own shots" on public.shots for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "Users manage their own putts" on public.putts for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "Users manage their own preferences" on public.preferences for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

create index if not exists shots_user_created_at_idx on public.shots (user_id, created_at desc);
create index if not exists putts_user_created_at_idx on public.putts (user_id, created_at desc);
