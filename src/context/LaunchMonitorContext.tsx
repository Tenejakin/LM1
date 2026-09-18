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
import {
  AprilTagCalibration,
  CalibrationCaptureStatus,
  CalibrationImageResult,
  CaptureAnalysis,
  BallDetection,
  CapturePreview,
  CaptureFramePreview,
  CaptureMode,
  ClubId,
  DeviceEvent,
  DeviceState,
  DeviceStatus,
  ExposureCalibrationResult,
  LensCalibrationResult,
  Putt,
  Shot,
  TargetLine,
  WifiConnectionStatus,
  WifiNetwork,
} from '@/types';
import { estimateShotFromCapture, normalizeShot } from '@/utils/carry';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';

const DEVICE_ID_KEY = '@pinpoint/ble-device-id';
const DEMO_KEY = '@pinpoint/demo-mode';
const CLUB_KEY = '@pinpoint/selected-club';
const RECONNECT_DELAY_MS = 3_000;

interface LaunchMonitorContextValue {
  captures: CaptureAnalysis[];
  state: DeviceState;
  status: DeviceStatus | null;
  shots: Shot[];
  activeShot: Shot | null;
  liveShot: Shot | null;
  putts: Putt[];
  activePutt: Putt | null;
  captureMode: CaptureMode;
  selectedClub: ClubId;
  deviceId: string | null;
  isDemo: boolean;
  error: string | null;
  previewFrame: string | null;
  previewDetection: { detection?: BallDetection; receivedAt: number } | null;
  previewAprilTag: { calibration?: AprilTagCalibration; receivedAt: number } | null;
  latestCalibrationImage: CalibrationImageResult | null;
  ballDetected: boolean;
  connect: () => Promise<void>;
  disconnect: () => void;
  enableDemo: () => void;
  arm: () => Promise<void>;
  armPutting: () => Promise<void>;
  disarm: () => Promise<void>;
  trigger: () => Promise<void>;
  setExposure: (exposureUs: number) => Promise<DeviceStatus>;
  setGain: (gain: number) => Promise<DeviceStatus>;
  autoCalibrateExposure: () => Promise<void>;
  /** The most recent automatic exposure result, or null before one has run. */
  exposureCalibration: ExposureCalibrationResult | null;
  clearExposureCalibration: () => void;
  resetBallCalibration: () => Promise<void>;
  captureAprilTagCalibration: () => Promise<AprilTagCalibration>;
  captureCalibrationImage: () => Promise<void>;
  clearCalibrationImages: () => Promise<CalibrationCaptureStatus>;
  runLensCalibration: () => Promise<LensCalibrationResult>;
  setTargetLine: () => Promise<TargetLine>;
  clearTargetLine: () => Promise<void>;
  getLatestCapturePreview: () => Promise<CapturePreview>;
  getCaptureFrame: (captureId: string, frameIndex: number) => Promise<CaptureFramePreview>;
  getCaptureContactSheet: (captureId: string) => Promise<CapturePreview>;
  getWifiStatus: () => Promise<WifiConnectionStatus>;
  scanWifi: () => Promise<WifiNetwork[]>;
  connectWifi: (ssid: string, password: string, hidden?: boolean) => Promise<WifiConnectionStatus>;
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
    sendCapture: sendCaptureToOpenGolfSim,
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
  const openGolfSimSentShotIdsRef = useRef(new Set<string>());

  openGolfSimStateRef.current = openGolfSimState;
  openGolfSimAutoSendRef.current = openGolfSimConfig.autoSend;

  const [state, setState] = useState<DeviceState>('offline');
  const [captures, setCaptures] = useState<CaptureAnalysis[]>([]);
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const shotsRef = useRef<Shot[]>([]);
  const [activeShot, setActiveShot] = useState<Shot | null>(null);
  const [liveShot, setLiveShot] = useState<Shot | null>(null);
  const [putts, setPutts] = useState<Putt[]>([]);
  const [activePutt, setActivePutt] = useState<Putt | null>(null);
  const [captureMode, setCaptureMode] = useState<CaptureMode>('full-shot');
  const [selectedClub, setSelectedClub] = useState<ClubId>('driver');
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewFrame, setPreviewFrame] = useState<string | null>(null);
  const [previewDetection, setPreviewDetection] = useState<{ detection?: BallDetection; receivedAt: number } | null>(null);
  const [previewAprilTag, setPreviewAprilTag] = useState<{ calibration?: AprilTagCalibration; receivedAt: number } | null>(null);
  const [latestCalibrationImage, setLatestCalibrationImage] = useState<CalibrationImageResult | null>(null);
  const [ballDetected, setBallDetected] = useState(false);
  const [exposureCalibration, setExposureCalibration] = useState<ExposureCalibrationResult | null>(null);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const handleEvent = useCallback((event: DeviceEvent) => {
    switch (event.type) {
      case 'capture':
        setCaptures((current) => [event.data, ...current.filter((item) => item.id !== event.data.id)].slice(0, 10));
        const estimatedShot = estimateShotFromCapture(
          event.data,
          selectedClubRef.current,
          (shotsRef.current[0]?.number ?? 0) + 1,
        );
        if (estimatedShot) {
          const nextShots = [estimatedShot, ...shotsRef.current.filter((shot) => shot.id !== estimatedShot.id)];
          shotsRef.current = nextShots;
          setShots(nextShots);
          setActiveShot(estimatedShot);
          setLiveShot(estimatedShot);
        } else {
          setActiveShot(null);
          setLiveShot(null);
        }
        // Send the same completed shot shown in the app. A motion-observed capture
        // always has clearly-labelled club estimates for unresolved camera metrics.
        if (openGolfSimStateRef.current === 'connected' && openGolfSimAutoSendRef.current) {
          if (estimatedShot) {
            if (sendShotToOpenGolfSim(estimatedShot)) {
              openGolfSimSentShotIdsRef.current.add(estimatedShot.id);
            }
          } else if (event.data.mode === 'putting') {
            sendCaptureToOpenGolfSim(event.data);
          }
        }
        break;
      case 'captureError':
        setError(event.data.message);
        break;
      case 'status':
        setStatus(event.data);
        setState(event.data.state);
        if (event.data.camera?.ballDetection) {
          setBallDetected(event.data.camera.ballDetection.state === 'detected');
        }
        break;
      case 'ballPresence':
        setBallDetected(event.data.present);
        break;
      case 'shot':
        const completedShot = normalizeShot(event.data, selectedClubRef.current);
        const nextShots = [completedShot, ...shotsRef.current.filter((shot) => shot.id !== completedShot.id)];
        shotsRef.current = nextShots;
        setShots(nextShots);
        setActiveShot(completedShot);
        setLiveShot(completedShot);
        setState('ready');
        setStatus((current) =>
          current ? { ...current, state: 'ready', lastSeenAt: new Date().toISOString() } : current,
        );
        if (
          openGolfSimStateRef.current === 'connected' &&
          openGolfSimAutoSendRef.current &&
          !openGolfSimSentShotIdsRef.current.has(completedShot.id)
        ) {
          if (sendShotToOpenGolfSim(completedShot)) {
            openGolfSimSentShotIdsRef.current.add(completedShot.id);
          }
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
      case 'preview':
        setPreviewFrame(`data:${event.data.mimeType};base64,${event.data.base64}`);
        setPreviewDetection({ detection: event.data.camera?.ballDetection, receivedAt: Date.now() });
        setPreviewAprilTag({ calibration: event.data.camera?.aprilTag, receivedAt: Date.now() });
        if (event.data.camera?.ballDetection) {
          setBallDetected(event.data.camera.ballDetection.state === 'detected');
        }
        if (event.data.camera?.model) {
          const camera = event.data.camera;
          setStatus((current) => current ? {
            ...current, camera, cameraConnected: true,
            fps: camera.fps ?? current.fps,
            exposureUs: camera.exposureUs ?? current.exposureUs,
          } : current);
        }
        break;
      case 'calibrationImage':
        setLatestCalibrationImage(event.data);
        break;
      case 'exposureCalibration':
        setExposureCalibration(event.data);
        break;
      case 'ready':
        setState('ready');
        sendOpenGolfSimDeviceStatus('ready');
        break;
    }
  }, [sendCaptureToOpenGolfSim, sendOpenGolfSimDeviceStatus, sendPuttToOpenGolfSim, sendShotToOpenGolfSim]);

  const connect = useCallback(
    async (preferredDeviceId?: string, quiet = false) => {
      clearReconnectTimer();
      intentionalDisconnect.current = false;
      setIsDemo(false);
      setCaptures([]);
      setPreviewFrame(null);
      setPreviewDetection(null);
      setPreviewAprilTag(null);
      setLatestCalibrationImage(null);
      setBallDetected(false);
      setError(null);
      if (!quiet) setState('connecting');

      try {
        let nextStatus = await client.current.connect(preferredDeviceId, handleEvent, () => {
          if (!mounted.current || intentionalDisconnect.current) return;
          setState('offline');
          setError('Bluetooth connection lost. Reconnecting…');
          reconnectTimer.current = setTimeout(() => {
            void reconnect.current(preferredDeviceId, true);
          }, RECONNECT_DELAY_MS);
        });

        if (!mounted.current) return;
        if (nextStatus.state === 'ready') nextStatus = await client.current.setClub(selectedClubRef.current);
        const connectedDeviceId = client.current.connectedDeviceId;
        setDeviceId(connectedDeviceId);
        setStatus(nextStatus);
        setState(nextStatus.state);
        setBallDetected(nextStatus.camera?.ballDetection?.state === 'detected');
        await AsyncStorage.setItem(DEMO_KEY, 'false');
        if (connectedDeviceId) {
          await AsyncStorage.setItem(DEVICE_ID_KEY, connectedDeviceId);
        }

        const [shotHistory, puttHistory] = await Promise.allSettled([
          client.current.listShots(),
          client.current.listPutts(),
        ]);
        if (nextStatus.protocolVersion && Number(nextStatus.protocolVersion.split('.')[1]) >= 13) {
          void client.current.listCaptures().then((history) => {
            if (mounted.current) setCaptures((current) => [...current, ...history.filter((item) => !current.some((existing) => existing.id === item.id))].slice(0, 10));
          }).catch((caught) => { if (mounted.current) setError(caught instanceof Error ? caught.message : 'Capture history unavailable.'); });
        }
        if (mounted.current) {
          if (shotHistory.status === 'fulfilled') {
            const nextShots = shotHistory.value.map((shot) =>
              normalizeShot(shot, selectedClubRef.current),
            );
            setShots(nextShots);
            shotsRef.current = nextShots;
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
    if (client.current.connectedDeviceId) {
      void client.current.setClub(clubId).catch((caught) => {
        setError(caught instanceof Error ? caught.message : 'Could not update the selected club on LM1.');
      });
    }
  }, []);

  const enableDemo = useCallback(() => {
    clearReconnectTimer();
    intentionalDisconnect.current = true;
    client.current.disconnect();
    setIsDemo(true);
    setStatus({ ...demoStatus, lastSeenAt: new Date().toISOString() });
    setState('ready');
    setShots(demoShots);
    shotsRef.current = demoShots;
    setActiveShot(demoShots[0] ?? null);
    setPutts(demoPutts);
    setActivePutt(demoPutts[0] ?? null);
    setError(null);
    setPreviewFrame(null);
    setPreviewDetection(null);
    setPreviewAprilTag(null);
    setBallDetected(false);
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
    setPreviewFrame(null);
    setPreviewDetection(null);
    setPreviewAprilTag(null);
    setBallDetected(false);
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
        setShots((current) => {
          const nextShots = [shot, ...current];
          shotsRef.current = nextShots;
          return nextShots;
        });
        setActiveShot(shot);
        setLiveShot(shot);
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

  const resetBallCalibration = useCallback(async () => {
    setError(null);
    if (isDemo) {
      throw new Error('Connect to LM1 to reset the camera empty plane.');
    }
    try {
      await client.current.resetBallCalibration();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not reset the camera empty plane.');
      throw caught;
    }
  }, [isDemo]);

  const setExposure = useCallback(async (exposureUs: number) => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to change the camera exposure.');
    try {
      const nextStatus = await client.current.setExposure(exposureUs);
      setStatus(nextStatus);
      setState(nextStatus.state);
      return nextStatus;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not change the camera exposure.');
      throw caught;
    }
  }, [isDemo]);

  const setGain = useCallback(async (gain: number) => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to change the camera gain.');
    try {
      const nextStatus = await client.current.setGain(gain);
      setStatus(nextStatus);
      setState(nextStatus.state);
      return nextStatus;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not change the camera gain.');
      throw caught;
    }
  }, [isDemo]);

  const autoCalibrateExposure = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to set the exposure automatically.');
    setExposureCalibration(null);
    try {
      await client.current.autoCalibrateExposure();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not set the exposure automatically.');
      throw caught;
    }
  }, [isDemo]);

  const clearExposureCalibration = useCallback(() => setExposureCalibration(null), []);

  const captureAprilTagCalibration = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to capture an AprilTag calibration.');
    try {
      return await client.current.captureAprilTagCalibration();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not capture the AprilTag calibration.');
      throw caught;
    }
  }, [isDemo]);

  const captureCalibrationImage = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to capture a lens calibration image.');
    try {
      await client.current.captureCalibrationImage();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not capture the calibration image.');
      throw caught;
    }
  }, [isDemo]);

  const clearCalibrationImages = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to clear calibration images.');
    try {
      const status = await client.current.clearCalibrationImages();
      setLatestCalibrationImage(null);
      return status;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not clear the calibration images.');
      throw caught;
    }
  }, [isDemo]);

  const runLensCalibration = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to run lens calibration.');
    try {
      return await client.current.runLensCalibration();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not run lens calibration.');
      throw caught;
    }
  }, [isDemo]);

  const setTargetLine = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to set the target line.');
    try {
      return await client.current.setTargetLine();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not set the target line.');
      throw caught;
    }
  }, [isDemo]);

  const clearTargetLine = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to clear the target line.');
    try {
      await client.current.clearTargetLine();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not clear the target line.');
      throw caught;
    }
  }, [isDemo]);

  const getLatestCapturePreview = useCallback(async () => {
    if (isDemo) throw new Error('Connect to LM1 to review an impact capture.');
    return client.current.getLatestCapturePreview();
  }, [isDemo]);

  const getCaptureFrame = useCallback(async (captureId: string, frameIndex: number) => {
    if (isDemo) throw new Error('Connect to LM1 to review capture frames.');
    return client.current.getCaptureFrame(captureId, frameIndex);
  }, [isDemo]);

  const getCaptureContactSheet = useCallback(async (captureId: string) => {
    if (isDemo) throw new Error('Connect to LM1 to review capture contact sheets.');
    return client.current.getCaptureContactSheet(captureId);
  }, [isDemo]);

  const getWifiStatus = useCallback(async () => client.current.getWifiStatus(), []);

  const scanWifi = useCallback(async () => client.current.scanWifi(), []);

  const connectWifi = useCallback(
    async (ssid: string, password: string, hidden = false) =>
      client.current.connectWifi(ssid, password, hidden),
    [],
  );

  const value = useMemo<LaunchMonitorContextValue>(
    () => ({
      captures,
      state,
      status,
      shots,
      activeShot,
      liveShot,
      putts,
      activePutt,
      captureMode,
      selectedClub,
      deviceId,
      isDemo,
      error,
      previewFrame,
      previewDetection,
      previewAprilTag,
      latestCalibrationImage,
      ballDetected,
      connect: () => connect(deviceId ?? undefined),
      disconnect,
      enableDemo,
      arm,
      armPutting,
      disarm,
      trigger,
      setExposure,
      setGain,
      autoCalibrateExposure,
      exposureCalibration,
      clearExposureCalibration,
      resetBallCalibration,
      captureAprilTagCalibration,
      captureCalibrationImage,
      clearCalibrationImages,
      runLensCalibration,
      setTargetLine,
      clearTargetLine,
      getLatestCapturePreview,
      getCaptureFrame,
      getCaptureContactSheet,
      getWifiStatus,
      scanWifi,
      connectWifi,
      selectShot: setActiveShot,
      selectClub,
      clearError: () => setError(null),
    }),
    [
      captures,
      state,
      status,
      shots,
      activeShot,
      liveShot,
      putts,
      activePutt,
      captureMode,
      selectedClub,
      deviceId,
      isDemo,
      error,
      previewFrame,
      previewDetection,
      previewAprilTag,
      latestCalibrationImage,
      ballDetected,
      connect,
      disconnect,
      enableDemo,
      arm,
      armPutting,
      disarm,
      trigger,
      setExposure,
      setGain,
      autoCalibrateExposure,
      exposureCalibration,
      clearExposureCalibration,
      resetBallCalibration,
      captureAprilTagCalibration,
      captureCalibrationImage,
      clearCalibrationImages,
      runLensCalibration,
      setTargetLine,
      clearTargetLine,
      getLatestCapturePreview,
      getCaptureFrame,
      getCaptureContactSheet,
      getWifiStatus,
      scanWifi,
      connectWifi,
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
