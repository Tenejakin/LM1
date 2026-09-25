create table public.shot_frames (
  user_id uuid not null,
  shot_id text not null,
  frame_index integer not null check (frame_index between 0 and 1999),
  frame_count integer not null check (frame_count between 1 and 2000),
  primary_path text not null,
  secondary_path text,
  time_ms numeric,
  pair_offset_us numeric,
  created_at timestamptz not null default now(),
  primary key (user_id, shot_id, frame_index),
  foreign key (user_id, shot_id) references public.shots (user_id, id) on delete cascade
);

alter table public.shot_frames enable row level security;
create policy "Users read their own shot frames" on public.shot_frames
  for select to authenticated using ((select auth.uid()) = user_id);
revoke all on public.shot_frames from public, anon, authenticated;
grant select on public.shot_frames to authenticated;

create table public.shot_frame_upload_tickets (
  user_id uuid not null,
  shot_id text not null,
  token_hash text not null unique,
  frame_count integer not null check (frame_count between 1 and 2000),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  primary key (user_id, shot_id),
  foreign key (user_id, shot_id) references public.shots (user_id, id) on delete cascade
);

alter table public.shot_frame_upload_tickets enable row level security;
revoke all on public.shot_frame_upload_tickets from public, anon, authenticated;
