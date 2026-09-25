alter table public.shots
  add column if not exists image_path text,
  add column if not exists secondary_image_path text;

comment on column public.shots.image_path is 'Private Bunny Storage path for the primary capture image.';
comment on column public.shots.secondary_image_path is 'Private Bunny Storage path for the upper camera capture image.';
