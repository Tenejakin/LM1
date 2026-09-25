# LM1 cloud deployment

The mobile app uses Supabase Auth and row-level security. Each signed-in user's
shots and putts are stored under that user's `auth.uid()`. The app uploads shot
images through the `shot-images` Edge Function, which checks the user's session
and shot ownership before accessing Bunny Storage. The Bunny password must
never be included in an Expo build.

## Database

Run migrations in order using Supabase SQL Editor, or apply them with the
Supabase CLI if the project is linked:

1. `migrations/20260924000100_initial_cloud_sync.sql` (already applied if you
   created the accounts and cloud tables earlier).
2. `migrations/20260924000200_shot_images.sql` (adds Bunny image paths to shots).
3. `migrations/20260924000300_preserve_shot_images.sql` (keeps image paths when shot data changes and adds the RLS-scoped shot sync function).
4. `migrations/20260924000400_shot_frames.sql` (private per-user original frame index and upload tickets).

## Edge Function secrets

In Supabase Dashboard, open **Edge Functions → Secrets** and set:

| Name | Value |
| --- | --- |
| `BUNNY_STORAGE_ENDPOINT` | `https://storage.bunnycdn.com/lm1-live` |
| `BUNNY_STORAGE_PASSWORD` | The **Password** from Bunny's Storage Zone Credentials (write access) |
| `BUNNY_STORAGE_READ_ONLY_PASSWORD` | Optional read-only password for fetching images |

The function uses `@supabase/server` with user authentication and a client
scoped to that user's row-level security policies. Do not copy Bunny passwords
into the Expo `EXPO_PUBLIC_` variables.

## Deploy the function

Deploy `functions/shot-images/index.ts` as `shot-images`. Disable the platform's
automatic JWT check for this function: `config.toml` sets
`[functions.shot-images] verify_jwt = false`. `@supabase/server` verifies the
user's Supabase token, and the function checks the user's row-level-secured shot
record before any Bunny operation. The automatic check cannot accept newer
`sb_publishable_` client keys.

With the Supabase CLI linked to the project:

```powershell
npx supabase functions deploy shot-images --no-verify-jwt
npx supabase functions deploy shot-frame-ingest --no-verify-jwt
```

The app then uploads each live shot's primary image and, when present, its upper
camera image. Failed uploads remain in an account-scoped local queue and retry
when the app returns to the foreground. Opening a saved shot fetches its images
through the same authenticated function. The Sessions screen displays only the
signed-in user's cloud history and shots recorded in that app session.

The contact sheet is a small overview of 12 moments. Original capture frames
are separate files under `shots/<user>/<shot>/frames/`, with one primary and,
for a two-camera capture, one secondary JPEG per frame index. The app obtains a
short-lived upload ticket for the signed-in shot and sends it to the Pi over
Bluetooth. The Pi uploads the original files to `shot-frame-ingest` over HTTPS;
the function checks the ticket, writes Bunny objects, and records frame paths
under that user's shot. An interrupted upload resumes from missing frame
indices. Shot review reads uploaded originals through the authenticated
`shot-images` function, with live Pi previews as a fallback.

If an older app build cleared an image path, the `repair` action checks that
user's expected Bunny object and restores the path. If Bunny has no image, a
connected Pi can provide a retained contact sheet for the app to re-upload.

For private images, keep this Storage Zone off a public Pull Zone, or enable
Bunny Token Authentication on any Pull Zone attached to it. The app does not
publish or use a CDN URL for these images.
