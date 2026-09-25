const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, apikey, x-client-info, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

const json = (status: number, value: unknown) => new Response(JSON.stringify(value), {
  status,
  headers: { ...corsHeaders, 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
});

function requiredEnv(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`${name} is not configured on the Edge Function.`);
  return value;
}

function toBase64(bytes: Uint8Array): string {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function fromBase64(value: string): Uint8Array<ArrayBuffer> {
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(value) || value.length > 8_000_000) {
    throw new Error('Invalid or oversized JPEG image.');
  }
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes.at(-2) !== 0xff || bytes.at(-1) !== 0xd9) {
    throw new Error('The uploaded file is not a JPEG image.');
  }
  return bytes;
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function storageEndpoint(): string {
  const endpoint = requiredEnv('BUNNY_STORAGE_ENDPOINT').replace(/\/+$/, '');
  const url = new URL(endpoint);
  if (url.protocol !== 'https:' || !url.hostname.endsWith('.bunnycdn.com') || !url.pathname.match(/^\/[A-Za-z0-9_-]+$/)) {
    throw new Error('BUNNY_STORAGE_ENDPOINT must be an HTTPS Bunny Storage Zone endpoint.');
  }
  return endpoint;
}

export default { fetch: withSupabase({ auth: 'user' }, async (request, ctx) => {
  if (request.method !== 'POST') return json(405, { error: 'Use POST.' });

  try {
    const userId = ctx.userClaims?.id;
    if (!userId) return json(401, { error: 'Sign in to access shot images.' });

    const body = await request.json() as { action?: string; shotId?: string; primaryBase64?: string; secondaryBase64?: string; camera?: string };
    if (!body.shotId || !/^[A-Za-z0-9_-]{1,128}$/.test(body.shotId)) return json(400, { error: 'Invalid shot ID.' });
    const { data: shot, error: shotError } = await ctx.supabase.from('shots')
      .select('data,image_path,secondary_image_path').eq('user_id', userId).eq('id', body.shotId).maybeSingle();
    if (shotError) return json(502, { error: 'Could not check shot ownership in Supabase.' });
    if (!shot) return json(404, { error: 'Shot was not found in your account.' });

    const endpoint = storageEndpoint();
    const bunnyPassword = requiredEnv('BUNNY_STORAGE_PASSWORD');
    if (body.action === 'startFrameUpload') {
      const frameCount = Number(shot.data?.frameCount);
      if (!Number.isInteger(frameCount) || frameCount < 1 || frameCount > 2000 || shot.data?.captureId !== body.shotId) {
        return json(400, { error: 'This shot has no valid saved frame sequence.' });
      }
      const tokenBytes = crypto.getRandomValues(new Uint8Array(32));
      const token = toBase64(tokenBytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      const expiresAt = new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString();
      const { error: ticketError } = await ctx.supabaseAdmin.from('shot_frame_upload_tickets').upsert({
        user_id: userId, shot_id: body.shotId, token_hash: await sha256(token), frame_count: frameCount, expires_at: expiresAt,
      }, { onConflict: 'user_id,shot_id' });
      if (ticketError) return json(502, { error: 'Could not start the frame upload.' });
      return json(200, { token, frameCount, expiresAt });
    }
    if (body.action === 'upload') {
      if (!body.primaryBase64) return json(400, { error: 'Primary capture image is required.' });
      const images: [string, string][] = [['image_path', body.primaryBase64]];
      if (body.secondaryBase64) images.push(['secondary_image_path', body.secondaryBase64]);
      const paths: Record<string, string> = {};
      for (const [column, base64] of images) {
        const bytes = fromBase64(base64);
        const suffix = column === 'image_path' ? 'primary' : 'secondary';
        const path = `shots/${userId}/${body.shotId}-${suffix}.jpg`;
        const upload = await fetch(`${endpoint}/${path}`, {
          method: 'PUT',
          headers: { AccessKey: bunnyPassword, 'Content-Type': 'image/jpeg' },
          body: bytes,
        });
        if (!upload.ok) return json(502, { error: `Bunny rejected the ${suffix} image upload (HTTP ${upload.status}).` });
        paths[column] = path;
      }
      const { error: updateError } = await ctx.supabase.from('shots').update(paths)
        .eq('user_id', userId).eq('id', body.shotId);
      if (updateError) return json(502, { error: 'Images uploaded, but Supabase could not save their paths. Retry the upload.' });
      return json(200, { imagePath: paths.image_path, secondaryImagePath: paths.secondary_image_path ?? null });
    }

    if (body.action === 'repair') {
      const paths: Record<string, string> = {};
      for (const [column, suffix] of [['image_path', 'primary'], ['secondary_image_path', 'secondary']] as const) {
        if (shot[column]) continue;
        const path = `shots/${userId}/${body.shotId}-${suffix}.jpg`;
        const check = await fetch(`${endpoint}/${path}`, { headers: { AccessKey: Deno.env.get('BUNNY_STORAGE_READ_ONLY_PASSWORD') || bunnyPassword } });
        if (check.status === 404) continue;
        if (!check.ok) return json(502, { error: `Bunny could not check the ${suffix} image (HTTP ${check.status}).` });
        await check.body?.cancel();
        paths[column] = path;
      }
      if (Object.keys(paths).length) {
        const { error: updateError } = await ctx.supabase.from('shots').update(paths)
          .eq('user_id', userId).eq('id', body.shotId);
        if (updateError) return json(502, { error: 'Bunny image was found, but Supabase could not save its path.' });
      }
      return json(200, {
        imagePath: paths.image_path ?? shot.image_path ?? null,
        secondaryImagePath: paths.secondary_image_path ?? shot.secondary_image_path ?? null,
      });
    }

    if (body.action === 'read') {
      const path = body.camera === 'secondary' ? shot.secondary_image_path : shot.image_path;
      const expectedPath = `shots/${userId}/${body.shotId}-${body.camera === 'secondary' ? 'secondary' : 'primary'}.jpg`;
      if (path !== expectedPath) return json(404, { error: 'This shot has no stored image.' });
      const read = await fetch(`${endpoint}/${path}`, { headers: { AccessKey: Deno.env.get('BUNNY_STORAGE_READ_ONLY_PASSWORD') || bunnyPassword } });
      if (!read.ok) return json(502, { error: `Bunny could not read this image (HTTP ${read.status}).` });
      return json(200, { mimeType: 'image/jpeg', base64: toBase64(new Uint8Array(await read.arrayBuffer())) });
    }
    if (body.action === 'readFrame') {
      const index = Number((body as { frameIndex?: number }).frameIndex);
      if (!Number.isInteger(index) || index < 0 || index >= 2000) return json(400, { error: 'Invalid frame index.' });
      const { data: frame, error: frameError } = await ctx.supabase.from('shot_frames').select('*')
        .eq('user_id', userId).eq('shot_id', body.shotId).eq('frame_index', index).maybeSingle();
      if (frameError) return json(502, { error: 'Could not read this shot frame.' });
      if (!frame) return json(404, { error: 'This frame has not been uploaded yet.' });
      const prefix = `shots/${userId}/${body.shotId}/frames/${String(index).padStart(4, '0')}`;
      if (frame.primary_path !== `${prefix}-primary.jpg` || (frame.secondary_path && frame.secondary_path !== `${prefix}-secondary.jpg`)) {
        return json(502, { error: 'The saved frame path is invalid.' });
      }
      const readKey = Deno.env.get('BUNNY_STORAGE_READ_ONLY_PASSWORD') || bunnyPassword;
      const primary = await fetch(`${endpoint}/${frame.primary_path}`, { headers: { AccessKey: readKey } });
      if (!primary.ok) return json(502, { error: `Bunny could not read this frame (HTTP ${primary.status}).` });
      let secondaryBase64: string | null = null;
      if (frame.secondary_path) {
        const secondary = await fetch(`${endpoint}/${frame.secondary_path}`, { headers: { AccessKey: readKey } });
        if (!secondary.ok) return json(502, { error: `Bunny could not read the upper frame (HTTP ${secondary.status}).` });
        secondaryBase64 = toBase64(new Uint8Array(await secondary.arrayBuffer()));
      }
      return json(200, {
        mimeType: 'image/jpeg', base64: toBase64(new Uint8Array(await primary.arrayBuffer())),
        secondaryBase64, captureId: body.shotId, frameIndex: index, frameCount: frame.frame_count,
        timeMs: frame.time_ms, pairOffsetUs: frame.pair_offset_us,
        impactFrameIndex: shot.data?.impactFrameIndex ?? null,
        coarseDepartureFrameIndex: shot.data?.coarseDepartureFrameIndex ?? null,
        lastStationaryFrameIndex: shot.data?.lastStationaryFrameIndex ?? null,
        firstMovingFrameIndex: shot.data?.firstMovingFrameIndex ?? null,
      });
    }
    return json(400, { error: 'Unknown image action.' });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Image request failed.';
    return json(400, { error: message });
  }
}) };
import { withSupabase } from 'npm:@supabase/server@1.8.0';
