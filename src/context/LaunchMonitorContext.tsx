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

import { createDemoShot, demoShots, demoStatus } from '@/data/demo';
import { createDemoPutt, demoPutts } from '@/data/puttingDemo';
import { isClubId } from '@/data/clubs';
import { DeviceClient } from '@/services/device';
import { CaptureMode, ClubId, DeviceEvent, DeviceState, DeviceStatus, Putt, Shot } from '@/types';
import { normalizeShot } from '@/utils/carry';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';

const DEVICE_ID_KEY = '@pinpoint/ble-device-id';
const DEMO_KEY = '@pinpoint/demo-mode';
const CLUB_KEY = '@pinpoint/selected-club';
const RECONNECT_DELAY_MS = 3_000;

interface LaunchMonitorContextValue {
  state: DeviceState;
  status: DeviceStatus | null;
  shots: Shot[];
  activeShot: Shot | null;
  putts: Putt[];
  activePutt: Putt | null;
  captureMode: CaptureMode;
  selectedClub: ClubId;
  deviceId: string | null;
  isDemo: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  enableDemo: () => void;
  arm: () => Promise<void>;
  armPutting: () => Promise<void>;
  disarm: () => Promise<void>;
  trigger: () => Promise<void>;
  selectShot: (shot: Shot) => void;
  selectClub: (clubId: ClubId) => void;
  clearError: () => void;
}

const LaunchMonitorContext = createContext<LaunchMonitorContextValue | null>(null);

export function LaunchMonitorProvider({ children }: PropsWithChildren) {
  const {
    state: openGolfSimState,
    config: openGolfSimConfig,
    sendShot: sendShotToOpenGolfSim,
    sendPutt: sendPuttToOpenGolfSim,
    sendDeviceStatus: sendOpenGolfSimDeviceStatus,
  } = useOpenGolfSim();
  const client = useRef(new DeviceClient());
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnect = useRef<(deviceId?: string, quiet?: boolean) => Promise<void>>(async () => {});
  const intentionalDisconnect = useRef(false);
  const mounted = useRef(true);
  const demoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectedClubRef = useRef<ClubId>('driver');
  const captureModeRef = useRef<CaptureMode>('full-shot');
  const openGolfSimStateRef = useRef(openGolfSimState);
  const openGolfSimAutoSendRef = useRef(openGolfSimConfig.autoSend);

  openGolfSimStateRef.current = openGolfSimState;
  openGolfSimAutoSendRef.current = openGolfSimConfig.autoSend;

  const [state, setState] = useState<DeviceState>('offline');
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [activeShot, setActiveShot] = useState<Shot | null>(null);
  const [putts, setPutts] = useState<Putt[]>([]);
  const [activePutt, setActivePutt] = useState<Putt | null>(null);
  const [captureMode, setCaptureMode] = useState<CaptureMode>('full-shot');
  const [selectedClub, setSelectedClub] = useState<ClubId>('driver');
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const handleEvent = useCallback((event: DeviceEvent) => {
    switch (event.type) {
      case 'status':
        setStatus(event.data);
        setState(event.data.state);
        break;
      case 'shot':
        const completedShot = normalizeShot(event.data, selectedClubRef.current);
        setShots((current) => [completedShot, ...current.filter((shot) => shot.id !== completedShot.id)]);
        setActiveShot(completedShot);
        setState('ready');
        setStatus((current) =>
          current ? { ...current, state: 'ready', lastSeenAt: new Date().toISOString() } : current,
        );
        if (openGolfSimStateRef.current === 'connected' && openGolfSimAutoSendRef.current) {
          sendShotToOpenGolfSim(completedShot);
        }
        sendOpenGolfSimDeviceStatus('ready');
        break;
      case 'putt':
        const completedPutt = event.data;
        setPutts((current) => [completedPutt, ...current.filter((putt) => putt.id !== completedPutt.id)]);
        setActivePutt(completedPutt);
        setState('ready');
        setStatus((current) =>
          current ? { ...current, state: 'ready', lastSeenAt: new Date().toISOString() } : current,
        );
        if (openGolfSimStateRef.current === 'connected' && openGolfSimAutoSendRef.current) {
          sendPuttToOpenGolfSim(completedPutt);
        }
        sendOpenGolfSimDeviceStatus('ready');
        break;
      case 'processing':
        setState('processing');
        sendOpenGolfSimDeviceStatus('busy');
        break;
      case 'ready':
        setState('ready');
        sendOpenGolfSimDeviceStatus('ready');
        break;
    }
  }, [sendOpenGolfSimDeviceStatus, sendPuttToOpenGolfSim, sendShotToOpenGolfSim]);

  const connect = useCallback(
    async (preferredDeviceId?: string, quiet = false) => {
      clearReconnectTimer();
      intentionalDisconnect.current = false;
      setIsDemo(false);
      setError(null);
      if (!quiet) setState('connecting');

      try {
        const nextStatus = await client.current.connect(preferredDeviceId, handleEvent, () => {
          if (!mounted.current || intentionalDisconnect.current) return;
          setState('offline');
          setError('Bluetooth connection lost. Reconnecting…');
          reconnectTimer.current = setTimeout(() => {
            void reconnect.current(preferredDeviceId, true);
          }, RECONNECT_DELAY_MS);
        });

        if (!mounted.current) return;
        const connectedDeviceId = client.current.connectedDeviceId;
        setDeviceId(connectedDeviceId);
        setStatus(nextStatus);
        setState(nextStatus.state);
        await AsyncStorage.setItem(DEMO_KEY, 'false');
        if (connectedDeviceId) {
          await AsyncStorage.setItem(DEVICE_ID_KEY, connectedDeviceId);
        }

        const [shotHistory, puttHistory] = await Promise.allSettled([
          client.current.listShots(),
          client.current.listPutts(),
        ]);
        if (mounted.current) {
          if (shotHistory.status === 'fulfilled') {
            const nextShots = shotHistory.value.map((shot) =>
              normalizeShot(shot, selectedClubRef.current),
            );
            setShots(nextShots);
            setActiveShot(nextShots[0] ?? null);
          }
          if (puttHistory.status === 'fulfilled') {
            setPutts(puttHistory.value);
            setActivePutt(puttHistory.value[0] ?? null);
          }
        }
      } catch (caught) {
        if (!mounted.current) return;
        const message = caught instanceof Error ? caught.message : 'Could not connect to the device.';
        setState(quiet ? 'offline' : 'error');
        setStatus(null);
        setError(quiet ? 'Device unavailable. Retrying…' : message);
        if (quiet && !intentionalDisconnect.current) {
          reconnectTimer.current = setTimeout(() => {
            void reconnect.current(preferredDeviceId, true);
          }, RECONNECT_DELAY_MS);
        }
      }
    },
    [clearReconnectTimer, handleEvent],
  );

  useEffect(() => {
    reconnect.current = connect;
  }, [connect]);

  const selectClub = useCallback((clubId: ClubId) => {
    selectedClubRef.current = clubId;
    setSelectedClub(clubId);
    void AsyncStorage.setItem(CLUB_KEY, clubId);
  }, []);

  const enableDemo = useCallback(() => {
    clearReconnectTimer();
    intentionalDisconnect.current = true;
    client.current.disconnect();
    setIsDemo(true);
    setStatus({ ...demoStatus, lastSeenAt: new Date().toISOString() });
    setState('ready');
    setShots(demoShots);
    setActiveShot(demoShots[0] ?? null);
    setPutts(demoPutts);
    setActivePutt(demoPutts[0] ?? null);
    setError(null);
    void AsyncStorage.setItem(DEMO_KEY, 'true');
  }, [clearReconnectTimer]);

  useEffect(() => {
    mounted.current = true;
    const currentClient = client.current;
    void (async () => {
      const [savedDeviceId, savedDemo, savedClub] = await Promise.all([
        AsyncStorage.getItem(DEVICE_ID_KEY),
        AsyncStorage.getItem(DEMO_KEY),
        AsyncStorage.getItem(CLUB_KEY),
      ]);
      if (!mounted.current) return;
      if (savedDeviceId) setDeviceId(savedDeviceId);
      if (isClubId(savedClub)) selectClub(savedClub);
      if (savedDemo === 'true') enableDemo();
    })();

    return () => {
      mounted.current = false;
      clearReconnectTimer();
      if (demoTimer.current) clearTimeout(demoTimer.current);
      currentClient.disconnect();
    };
  }, [clearReconnectTimer, enableDemo, selectClub]);

  const disconnect = useCallback(() => {
    intentionalDisconnect.current = true;
    clearReconnectTimer();
    client.current.disconnect();
    setIsDemo(false);
    setStatus(null);
    setState('offline');
    setError(null);
    void AsyncStorage.setItem(DEMO_KEY, 'false');
  }, [clearReconnectTimer]);

  const arm = useCallback(async () => {
    setError(null);
    captureModeRef.current = 'full-shot';
    setCaptureMode('full-shot');
    if (isDemo) {
      setState('armed');
      setStatus((current) => (current ? { ...current, state: 'armed' } : current));
      return;
    }
    try {
      const nextStatus = await client.current.arm(selectedClub, 'full-shot');
      setStatus(nextStatus);
      setState(nextStatus.state);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not arm the device.');
    }
  }, [isDemo, selectedClub]);

  const armPutting = useCallback(async () => {
    setError(null);
    captureModeRef.current = 'putting';
    setCaptureMode('putting');
    if (isDemo) {
      setState('armed');
      setStatus((current) => (current ? { ...current, state: 'armed' } : current));
      return;
    }
    try {
      const nextStatus = await client.current.arm('putter', 'putting');
      setStatus(nextStatus);
      setState(nextStatus.state);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not arm putting mode.');
    }
  }, [isDemo]);

  const disarm = useCallback(async () => {
    setError(null);
    if (isDemo) {
      setState('ready');
      setStatus((current) => (current ? { ...current, state: 'ready' } : current));
      return;
    }
    try {
      const nextStatus = await client.current.disarm();
      setStatus(nextStatus);
      setState(nextStatus.state);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not disarm the device.');
    }
  }, [isDemo]);

  const trigger = useCallback(async () => {
    setError(null);
    if (isDemo) {
      setState('processing');
      sendOpenGolfSimDeviceStatus('busy');
      setStatus((current) => (current ? { ...current, state: 'processing' } : current));
      demoTimer.current = setTimeout(() => {
        if (captureModeRef.current === 'putting') {
          const nextNumber = (putts[0]?.number ?? 0) + 1;
          const putt = createDemoPutt(nextNumber);
          setPutts((current) => [putt, ...current]);
          setActivePutt(putt);
          setState('ready');
          setStatus((current) =>
            current
              ? { ...current, state: 'ready', lastSeenAt: new Date().toISOString() }
              : current,
          );
          if (openGolfSimStateRef.current === 'connected' && openGolfSimAutoSendRef.current) {
            sendPuttToOpenGolfSim(putt);
          }
          sendOpenGolfSimDeviceStatus('ready');
          return;
        }
        const nextNumber = (shots[0]?.number ?? 0) + 1;
        const shot = createDemoShot(nextNumber, selectedClub);
        setShots((current) => [shot, ...current]);
        setActiveShot(shot);
        setState('ready');
        setStatus((current) =>
          current
            ? { ...current, state: 'ready', lastSeenAt: new Date().toISOString() }
            : current,
        );
        if (openGolfSimStateRef.current === 'connected' && openGolfSimAutoSendRef.current) {
          sendShotToOpenGolfSim(shot);
        }
        sendOpenGolfSimDeviceStatus('ready');
      }, 1_100);
      return;
    }
    try {
      setState('processing');
      sendOpenGolfSimDeviceStatus('busy');
      await client.current.trigger();
    } catch (caught) {
      setState(status?.state ?? 'ready');
      setError(caught instanceof Error ? caught.message : 'The manual trigger failed.');
    }
  }, [
    isDemo,
    putts,
    selectedClub,
    sendOpenGolfSimDeviceStatus,
    sendPuttToOpenGolfSim,
    sendShotToOpenGolfSim,
    shots,
    status?.state,
  ]);

  const value = useMemo<LaunchMonitorContextValue>(
    () => ({
      state,
      status,
      shots,
      activeShot,
      putts,
      activePutt,
      captureMode,
      selectedClub,
      deviceId,
      isDemo,
      error,
      connect: () => connect(deviceId ?? undefined),
      disconnect,
      enableDemo,
      arm,
      armPutting,
      disarm,
      trigger,
      selectShot: setActiveShot,
      selectClub,
      clearError: () => setError(null),
    }),
    [
      state,
      status,
      shots,
      activeShot,
      putts,
      activePutt,
      captureMode,
      selectedClub,
      deviceId,
      isDemo,
      error,
      connect,
      disconnect,
      enableDemo,
      arm,
      armPutting,
      disarm,
      trigger,
      selectClub,
    ],
  );

  return <LaunchMonitorContext.Provider value={value}>{children}</LaunchMonitorContext.Provider>;
}

export function useLaunchMonitor(): LaunchMonitorContextValue {
  const value = useContext(LaunchMonitorContext);
  if (!value) {
    throw new Error('useLaunchMonitor must be used inside LaunchMonitorProvider.');
  }
  return value;
}
