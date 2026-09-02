import AsyncStorage from '@react-native-async-storage/async-storage';
import React, {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { OpenGolfSimClient } from '@/services/opengolfsim';
import {
  OpenGolfSimConfig,
  OpenGolfSimResult,
  OpenGolfSimState,
  Putt,
  Shot,
} from '@/types';

const CONFIG_KEY = '@pinpoint/opengolfsim-config';

const DEFAULT_CONFIG: OpenGolfSimConfig = {
  mode: 'desktop',
  accountEmail: '',
  bridgeAddress: '',
  autoSend: true,
};

interface OpenGolfSimContextValue {
  state: OpenGolfSimState;
  config: OpenGolfSimConfig;
  error: string | null;
  playerClub: string | null;
  lastResult: OpenGolfSimResult | null;
  lastSentAt: string | null;
  connect: (config: OpenGolfSimConfig) => Promise<void>;
  disconnect: () => void;
  setAutoSend: (enabled: boolean) => void;
  sendShot: (shot: Shot) => boolean;
  sendPutt: (putt: Putt) => boolean;
  sendTestShot: () => boolean;
  sendDeviceStatus: (status: 'ready' | 'busy') => void;
  clearError: () => void;
}

const OpenGolfSimContext = createContext<OpenGolfSimContextValue | null>(null);

function isSavedConfig(value: unknown): value is OpenGolfSimConfig {
  if (!value || typeof value !== 'object') return false;
  const config = value as Partial<OpenGolfSimConfig>;
  return (
    (config.mode === 'web' || config.mode === 'desktop') &&
    typeof config.accountEmail === 'string' &&
    typeof config.bridgeAddress === 'string' &&
    typeof config.autoSend === 'boolean'
  );
}

export function OpenGolfSimProvider({ children }: PropsWithChildren) {
  const client = useRef(new OpenGolfSimClient());
  const mounted = useRef(true);
  const [state, setState] = useState<OpenGolfSimState>('offline');
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [error, setError] = useState<string | null>(null);
  const [playerClub, setPlayerClub] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<OpenGolfSimResult | null>(null);
  const [lastSentAt, setLastSentAt] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    const activeClient = client.current;
    void (async () => {
      const saved = await AsyncStorage.getItem(CONFIG_KEY);
      if (!saved || !mounted.current) return;
      try {
        const parsed: unknown = JSON.parse(saved);
        if (isSavedConfig(parsed)) setConfig(parsed);
      } catch {
        // Ignore invalid legacy settings and keep safe defaults.
      }
    })();

    return () => {
      mounted.current = false;
      activeClient.disconnect();
    };
  }, []);

  const connect = useCallback(async (nextConfig: OpenGolfSimConfig) => {
    const normalized: OpenGolfSimConfig = {
      ...nextConfig,
      accountEmail: nextConfig.accountEmail.trim(),
      bridgeAddress: nextConfig.bridgeAddress.trim(),
    };
    setConfig(normalized);
    setState('connecting');
    setError(null);
    setPlayerClub(null);

    try {
      await client.current.connect(normalized, {
        onDisconnect: (message) => {
          if (!mounted.current) return;
          setState('error');
          setError(message);
        },
        onPlayerClub: setPlayerClub,
        onResult: setLastResult,
      });
      if (!mounted.current) return;
      setState('connected');
      void AsyncStorage.setItem(CONFIG_KEY, JSON.stringify(normalized));
    } catch (caught) {
      if (!mounted.current) return;
      setState('error');
      setError(caught instanceof Error ? caught.message : 'Could not connect to OpenGolfSim.');
    }
  }, []);

  const disconnect = useCallback(() => {
    client.current.disconnect();
    setState('offline');
    setError(null);
    setPlayerClub(null);
  }, []);

  const setAutoSend = useCallback((enabled: boolean) => {
    setConfig((current) => {
      const next = { ...current, autoSend: enabled };
      void AsyncStorage.setItem(CONFIG_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const sendShot = useCallback((shot: Shot): boolean => {
    try {
      client.current.sendShot(shot);
      setLastSentAt(new Date().toISOString());
      setError(null);
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not send the shot to OpenGolfSim.');
      return false;
    }
  }, []);

  const sendPutt = useCallback((putt: Putt): boolean => {
    try {
      client.current.sendPutt(putt);
      setLastSentAt(new Date().toISOString());
      setError(null);
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not send the putt to OpenGolfSim.');
      return false;
    }
  }, []);

  const sendTestShot = useCallback((): boolean => {
    try {
      client.current.sendTestShot();
      setLastSentAt(new Date().toISOString());
      setError(null);
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not send the OpenGolfSim test shot.');
      return false;
    }
  }, []);

  const sendDeviceStatus = useCallback((status: 'ready' | 'busy') => {
    try {
      client.current.sendDeviceStatus(status);
    } catch {
      // Status is best-effort; shot sending reports actionable errors separately.
    }
  }, []);

  const value = useMemo<OpenGolfSimContextValue>(
    () => ({
      state,
      config,
      error,
      playerClub,
      lastResult,
      lastSentAt,
      connect,
      disconnect,
      setAutoSend,
      sendShot,
      sendPutt,
      sendTestShot,
      sendDeviceStatus,
      clearError: () => setError(null),
    }),
    [
      state,
      config,
      error,
      playerClub,
      lastResult,
      lastSentAt,
      connect,
      disconnect,
      setAutoSend,
      sendShot,
      sendPutt,
      sendTestShot,
      sendDeviceStatus,
    ],
  );

  return <OpenGolfSimContext.Provider value={value}>{children}</OpenGolfSimContext.Provider>;
}

export function useOpenGolfSim(): OpenGolfSimContextValue {
  const value = useContext(OpenGolfSimContext);
  if (!value) throw new Error('useOpenGolfSim must be used inside OpenGolfSimProvider.');
  return value;
}
