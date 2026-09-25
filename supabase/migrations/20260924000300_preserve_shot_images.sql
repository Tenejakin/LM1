-- Existing app builds upsert shot data without image columns. Keep image paths
-- intact until those builds are replaced.
create or replace function public.preserve_shot_image_paths()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.image_path := coalesce(new.image_path, old.image_path);
  new.secondary_image_path := coalesce(new.secondary_image_path, old.secondary_image_path);
  return new;
end;
$$;

create trigger preserve_shot_image_paths_before_update
before update on public.shots
for each row execute function public.preserve_shot_image_paths();

-- New app builds update only the shot JSON on conflict, leaving image paths
-- untouched. SECURITY INVOKER keeps the shots table's user RLS in force.
create or replace function public.sync_shots(p_shots jsonb)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if (select auth.uid()) is null then
    raise exception 'Sign in to sync shots.' using errcode = '28000';
  end if;
  if jsonb_typeof(p_shots) is distinct from 'array' then
    raise exception 'Shot payload must be an array.' using errcode = '22023';
  end if;

  insert into public.shots (user_id, id, data)
  select (select auth.uid()), shot.value->>'id', shot.value
  from jsonb_array_elements(p_shots) as shot(value)
  where nullif(shot.value->>'id', '') is not null
  on conflict (user_id, id) do update set data = excluded.data;
end;
$$;

revoke all on function public.sync_shots(jsonb) from public, anon;
grant execute on function public.sync_shots(jsonb) to authenticated;
