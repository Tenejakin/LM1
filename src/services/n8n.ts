import type { CaptureAnalysis, N8nCapturePayload, N8nShotPayload, Shot } from '@/types';

const APP_VERSION = '3.12.0';
const REQUEST_TIMEOUT_MS = 15_000;

export function normalizeWebhookUrl(value: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error('Enter an n8n webhook URL first.');

  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error('Enter a valid n8n webhook URL.');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('The n8n webhook must use HTTP or HTTPS.');
  }
  return parsed.toString();
}

export function createN8nShotPayload(shot: Shot, sentAt = new Date().toISOString()): N8nShotPayload {
  return {
    event: 'lm1.shot',
    schemaVersion: 1,
    sentAt,
    source: { app: 'LM1', appVersion: APP_VERSION },
    shot,
  };
}

export function createN8nCapturePayload(
  capture: CaptureAnalysis,
  sentAt = new Date().toISOString(),
): N8nCapturePayload {
  return {
    event: 'lm1.capture',
    schemaVersion: 1,
    sentAt,
    source: { app: 'LM1', appVersion: APP_VERSION },
    capture,
  };
}

async function postToN8n(webhookUrl: string, payload: N8nShotPayload | N8nCapturePayload): Promise<void> {
  const url = normalizeWebhookUrl(webhookUrl);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`n8n returned HTTP ${response.status}.`);
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('The n8n webhook timed out.');
    }
    throw error instanceof Error ? error : new Error('Could not send the shot to n8n.');
  } finally {
    clearTimeout(timeout);
  }
}

export async function postShotToN8n(webhookUrl: string, shot: Shot): Promise<void> {
  await postToN8n(webhookUrl, createN8nShotPayload(shot));
}

export async function postCaptureToN8n(webhookUrl: string, capture: CaptureAnalysis): Promise<void> {
  await postToN8n(webhookUrl, createN8nCapturePayload(capture));
}
