import { withSupabase } from 'npm:@supabase/server@1.8.0';

const json = (status: number, value: unknown) => Response.json(value, {
  status,
  headers: { 'Cache-Control': 'no-store' },
});

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function jpegBytes(base64: string): Uint8Array<ArrayBuffer> {
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(base64) || base64.length > 8_000_000) throw new Error('Invalid or oversized JPEG frame.');
  const raw = atob(base64);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes.at(-2) !== 0xff || bytes.at(-1) !== 0xd9) {
    throw new Error('Frame is not a complete JPEG.');
  }
  return bytes;
}

function bunnyEndpoint(): string {
  const endpoint = Deno.env.get('BUNNY_STORAGE_ENDPOINT')?.replace(/\/+$/, '');
  if (!endpoint) throw new Error('Bunny endpoint is not configured.');
  const url = new URL(endpoint);
  if (url.protocol !== 'https:' || !url.hostname.endsWith('.bunnycdn.com') || !/^\/[A-Za-z0-9_-]+$/.test(url.pathname)) {
    throw new Error('Invalid Bunny Storage endpoint.');
  }
  return endpoint;
}

export default { fetch: withSupabase({ auth: 'none' }, async (request, ctx) => {
  if (request.method !== 'POST') return json(405, { error: 'Use POST.' });
  const token = request.headers.get('x-upload-token') || '';
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) return json(401, { error: 'Invalid frame upload ticket.' });

  try {
    const { data: ticket, error: ticketError } = await ctx.supabaseAdmin.from('shot_frame_upload_tickets')
      .select('user_id,shot_id,frame_count,expires_at').eq('token_hash', await sha256(token)).maybeSingle();
    if (ticketError) return json(502, { error: 'Could not check the upload ticket.' });
    if (!ticket || Date.parse(ticket.expires_at) <= Date.now()) return json(401, { error: 'Frame upload ticket expired or invalid.' });

    const body = await request.json() as {
      captureId?: string; frameIndex?: number; frameCount?: number; primaryBase64?: string;
      secondaryBase64?: string; timeMs?: number | null; pairOffsetUs?: number | null;
    };
    if (body.captureId !== ticket.shot_id || !Number.isInteger(body.frameIndex)
      || body.frameIndex! < 0 || body.frameIndex! >= ticket.frame_count || body.frameCount !== ticket.frame_count
      || !body.primaryBase64) return json(400, { error: 'Frame does not match the upload ticket.' });
    const index = body.frameIndex!;
    const endpoint = bunnyEndpoint();
    const password = Deno.env.get('BUNNY_STORAGE_PASSWORD');
    if (!password) throw new Error('Bunny password is not configured.');
    const prefix = `shots/${ticket.user_id}/${ticket.shot_id}/frames/${String(index).padStart(4, '0')}`;
    const frames: [string, string][] = [['primary_path', body.primaryBase64]];
    if (body.secondaryBase64) frames.push(['secondary_path', body.secondaryBase64]);
    const paths: Record<string, string> = {};
    for (const [column, base64] of frames) {
      const suffix = column === 'primary_path' ? 'primary' : 'secondary';
      const path = `${prefix}-${suffix}.jpg`;
      const upload = await fetch(`${endpoint}/${path}`, {
        method: 'PUT', headers: { AccessKey: password, 'Content-Type': 'image/jpeg' }, body: jpegBytes(base64),
      });
      if (!upload.ok) return json(502, { error: `Bunny rejected ${suffix} frame ${index} (HTTP ${upload.status}).` });
      paths[column] = path;
    }
    const timeMs = body.timeMs == null ? null : Number(body.timeMs);
    const pairOffsetUs = body.pairOffsetUs == null ? null : Number(body.pairOffsetUs);
    if ((timeMs != null && (!Number.isFinite(timeMs) || timeMs < 0))
      || (pairOffsetUs != null && !Number.isFinite(pairOffsetUs))) return json(400, { error: 'Invalid frame timing.' });
    const { error: rowError } = await ctx.supabaseAdmin.from('shot_frames').upsert({
      user_id: ticket.user_id, shot_id: ticket.shot_id, frame_index: index, frame_count: ticket.frame_count,
      primary_path: paths.primary_path, secondary_path: paths.secondary_path ?? null,
      time_ms: timeMs, pair_offset_us: pairOffsetUs,
    }, { onConflict: 'user_id,shot_id,frame_index' });
    if (rowError) return json(502, { error: 'Bunny stored this frame, but Supabase could not save its path.' });
    return json(200, { frameIndex: index });
  } catch (caught) {
    return json(400, { error: caught instanceof Error ? caught.message : 'Frame upload failed.' });
  }
}) };
