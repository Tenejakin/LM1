import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { normalizeWebhookUrl, postCaptureToN8n, postShotToN8n } from '@/services/n8n';
import type { CaptureAnalysis, N8nConfig, Shot } from '@/types';

const CONFIG_KEY = '@pinpoint/n8n-config';
const DEFAULT_CONFIG: N8nConfig = { webhookUrl: '' };

interface N8nContextValue {
  config: N8nConfig;
  ready: boolean;
  lastSentAt: string | null;
  saveConfig: (config: N8nConfig) => Promise<void>;
  sendShot: (shot: Shot) => Promise<void>;
  sendCapture: (capture: CaptureAnalysis) => Promise<void>;
}

const N8nContext = createContext<N8nContextValue | null>(null);

export function N8nProvider({ children }: PropsWithChildren) {
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [lastSentAt, setLastSentAt] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void AsyncStorage.getItem(CONFIG_KEY).then((saved) => {
      if (!active || !saved) return;
      try {
        const parsed = JSON.parse(saved) as Partial<N8nConfig>;
        if (typeof parsed.webhookUrl === 'string') setConfig({ webhookUrl: parsed.webhookUrl });
      } catch {
        // Ignore invalid legacy settings and keep the endpoint empty.
      }
    });
    return () => { active = false; };
  }, []);

  const saveConfig = useCallback(async (next: N8nConfig) => {
    const normalized = { webhookUrl: normalizeWebhookUrl(next.webhookUrl) };
    await AsyncStorage.setItem(CONFIG_KEY, JSON.stringify(normalized));
    setConfig(normalized);
  }, []);

  const sendShot = useCallback(async (shot: Shot) => {
    await postShotToN8n(config.webhookUrl, shot);
    setLastSentAt(new Date().toISOString());
  }, [config.webhookUrl]);

  const sendCapture = useCallback(async (capture: CaptureAnalysis) => {
    await postCaptureToN8n(config.webhookUrl, capture);
    setLastSentAt(new Date().toISOString());
  }, [config.webhookUrl]);

  const value = useMemo<N8nContextValue>(() => ({
    config,
    ready: Boolean(config.webhookUrl),
    lastSentAt,
    saveConfig,
    sendShot,
    sendCapture,
  }), [config, lastSentAt, saveConfig, sendShot, sendCapture]);

  return <N8nContext.Provider value={value}>{children}</N8nContext.Provider>;
}

export function useN8n(): N8nContextValue {
  const value = useContext(N8nContext);
  if (!value) throw new Error('useN8n must be used inside N8nProvider.');
  return value;
}
