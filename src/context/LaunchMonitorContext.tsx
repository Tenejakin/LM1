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
  BagClub,
  CalibrationCamera,
  CalibrationCaptureStatus,
  CalibrationImageResult,
  CaptureAnalysis,
  BallDetection,
  CapturePreview,
  CaptureClip,
  CaptureFramePreview,
  CaptureMode,
  ClubId,
  DeviceEvent,
  DeviceState,
  DeviceStatus,
  LightMode,
  FrameUploadProgress,
  ExposureCalibrationResult,
  LensCalibrationResult,
  PracticeSession,
  ReferenceShotData,
  StereoCalibrationAction,
  StereoCalibrationOptions,
  StereoCalibrationStatus,
  Putt,
  Shot,
  ShotCoverage,
  TargetLine,
  WifiConnectionStatus,
  WifiNetwork,
} from '@/types';
import { estimateShotFromCapture, normalizeShot } from '@/utils/carry';
import { bagClubCommand, parseBagClubs } from '@/utils/bagClubs';
import { puttFromCapture } from '@/utils/puttCapture';
import { defaultSessionName, newSessionId, parseSessions } from '@/utils/sessions';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';
import { useCloudSync } from '@/context/CloudSyncContext';

const DEVICE_ID_KEY = '@pinpoint/ble-device-id';
const DEMO_KEY = '@pinpoint/demo-mode';
const CLUB_KEY = '@pinpoint/selected-club';
const BAG_CLUBS_KEY = '@pinpoint/bag-clubs';
const SELECTED_BAG_CLUB_KEY = '@pinpoint/selected-bag-club';
/** Cloud preference key; the list follows the signed-in account. */
const BAG_CLUBS_PREFERENCE = 'bagClubs';
const SESSIONS_KEY = '@pinpoint/sessions';
const ACTIVE_SESSION_KEY = '@pinpoint/active-session';
/** Cloud preference key; sessions follow the signed-in account like the club list. */
const SESSIONS_PREFERENCE = 'sessions';
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
  /** Named clubs the player added, e.g. several sand wedges under test. */
  bagClubs: BagClub[];
  /** The selected named club, or null when a plain club type is selected. */
  selectedBagClub: BagClub | null;
  deviceId: string | null;
  isDemo: boolean;
  error: string | null;
  previewFrame: string | null;
  secondaryPreviewFrame: string | null;
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
  setLightMode: (mode: LightMode) => Promise<DeviceStatus>;
  autoCalibrateExposure: () => Promise<void>;
  /** The most recent automatic exposure result, or null before one has run. */
  exposureCalibration: ExposureCalibrationResult | null;
  clearExposureCalibration: () => void;
  resetBallCalibration: () => Promise<void>;
  captureAprilTagCalibration: () => Promise<AprilTagCalibration>;
  captureCalibrationImage: (camera?: CalibrationCamera) => Promise<void>;
  clearCalibrationImages: (camera?: CalibrationCamera) => Promise<CalibrationCaptureStatus>;
  runLensCalibration: (camera?: CalibrationCamera) => Promise<LensCalibrationResult>;
  stereoCalibration: (action: StereoCalibrationAction, options?: StereoCalibrationOptions) => Promise<StereoCalibrationStatus>;
  getShotCoverage: () => Promise<ShotCoverage>;
  setTargetLine: () => Promise<TargetLine>;
  clearTargetLine: () => Promise<void>;
  getLatestCapturePreview: () => Promise<CapturePreview>;
  getCaptureFrame: (captureId: string, frameIndex: number) => Promise<CaptureFramePreview>;
  getCaptureClip: (captureId: string, startFrame: number, count: number) => Promise<CaptureClip>;
  getCaptureContactSheet: (captureId: string) => Promise<CapturePreview>;
  getLatestPuttRecoveryCandidate: () => Promise<Putt | null>;
  saveRecoveredPutt: (putt: Putt) => Promise<void>;
  retryShotImage: (shot: Shot) => Promise<string>;
  /** Leave a shot out of session averages, dispersion and gapping (kept in history). */
  setShotExcluded: (shotId: string, excluded: boolean) => void;
  /** Every session on this device and account. */
  sessions: PracticeSession[];
  /** The open session new shots are filed under, or null. */
  activeSession: PracticeSession | null;
  startSession: (draft: { name?: string; referenceDevice?: string; notes?: string }) => PracticeSession;
  endSession: () => void;
  /** Reopen a closed session so new shots join it; closes any other open session. */
  resumeSession: (sessionId: string) => void;
  updateSession: (session: PracticeSession) => void;
  /** Removes the session; its shots stay in history without a session. */
  deleteSession: (sessionId: string) => void;
  setShotSession: (shotId: string, sessionId: string | null) => void;
  /** Numbers typed in from another launch monitor for this swing; null clears them. */
  setShotReference: (shotId: string, reference: ReferenceShotData | null) => void;
  frameUploadProgress: Record<string, FrameUploadProgress>;
  startShotFrameUpload: (shot: Shot) => Promise<FrameUploadProgress>;
  getWifiStatus: () => Promise<WifiConnectionStatus>;
  scanWifi: () => Promise<WifiNetwork[]>;
  connectWifi: (ssid: string, password: string, hidden?: boolean) => Promise<WifiConnectionStatus>;
  selectShot: (shot: Shot) => void;
  selectClub: (clubId: ClubId) => void;
  selectBagClub: (bagClubId: string) => void;
  saveBagClub: (club: BagClub) => void;
  deleteBagClub: (bagClubId: string) => void;
  clearError: () => void;
}

const LaunchMonitorContext = createContext<LaunchMonitorContextValue | null>(null);

export function LaunchMonitorProvider({ children }: PropsWithChildren) {
  const { session, syncShots, syncPutts, restoreShots, restorePutts, uploadShotCapture, repairShotImage, beginFrameUpload, getUploadedFrameIndices, savePreference, restorePreferences } = useCloudSync();
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
  const selectedBagClubRef = useRef<BagClub | null>(null);
  const bagClubsRef = useRef<BagClub[]>([]);
  const captureModeRef = useRef<CaptureMode>('full-shot');
  const openGolfSimStateRef = useRef(openGolfSimState);
  const openGolfSimAutoSendRef = useRef(openGolfSimConfig.autoSend);
  const openGolfSimSentShotIdsRef = useRef(new Set<string>());
  const imageRecoveryAttemptedRef = useRef(new Set<string>());
  const frameUploadAttemptedRef = useRef(new Set<string>());
  const lastSavedPiSettingsRef = useRef<string | null>(null);

  openGolfSimStateRef.current = openGolfSimState;
  openGolfSimAutoSendRef.current = openGolfSimConfig.autoSend;

  const [state, setState] = useState<DeviceState>('offline');
  const [captures, setCaptures] = useState<CaptureAnalysis[]>([]);
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const shotsRef = useRef<Shot[]>([]);
  const demoOriginalShots = useRef<Shot[] | null>(null);
  const demoOriginalPutts = useRef<Putt[] | null>(null);
  const [activeShot, setActiveShot] = useState<Shot | null>(null);
  const [liveShot, setLiveShot] = useState<Shot | null>(null);
  const [putts, setPutts] = useState<Putt[]>([]);
  const puttsRef = useRef<Putt[]>([]);
  puttsRef.current = putts;
  const [activePutt, setActivePutt] = useState<Putt | null>(null);
  const [captureMode, setCaptureMode] = useState<CaptureMode>('full-shot');
  const [selectedClub, setSelectedClub] = useState<ClubId>('driver');
  const [bagClubs, setBagClubs] = useState<BagClub[]>([]);
  const [selectedBagClub, setSelectedBagClub] = useState<BagClub | null>(null);
  const [sessions, setSessions] = useState<PracticeSession[]>([]);
  const sessionsRef = useRef<PracticeSession[]>([]);
  const [activeSession, setActiveSession] = useState<PracticeSession | null>(null);
  const activeSessionRef = useRef<PracticeSession | null>(null);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [frameUploadProgress, setFrameUploadProgress] = useState<Record<string, FrameUploadProgress>>({});
  const [previewFrame, setPreviewFrame] = useState<string | null>(null);
  const [secondaryPreviewFrame, setSecondaryPreviewFrame] = useState<string | null>(null);
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
        if (event.data.mode === 'putting') {
          const capturedPutt = puttFromCapture(event.data, (puttsRef.current[0]?.number ?? 0) + 1);
          if (capturedPutt && !puttsRef.current.some((putt) => putt.id === capturedPutt.id)) {
            const nextPutts = [capturedPutt, ...puttsRef.current];
            puttsRef.current = nextPutts;
            setPutts(nextPutts);
            setActivePutt(capturedPutt);
            void syncPutts([capturedPutt]).catch((caught) => setError(`Putt cloud sync failed: ${caught instanceof Error ? caught.message : 'Unknown error.'}`));
          }
        }
        const estimatedShot = estimateShotFromCapture(
          event.data,
          selectedClubRef.current,
          (shotsRef.current[0]?.number ?? 0) + 1,
        );
        if (estimatedShot) {
          // A capture re-sent for a shot already held must not wipe what the player added to it.
          const existing = shotsRef.current.find((shot) => shot.id === estimatedShot.id);
          if (existing) {
            estimatedShot.number = existing.number;
            if (existing.sessionId) estimatedShot.sessionId = existing.sessionId;
            if (existing.reference) estimatedShot.reference = existing.reference;
            if (existing.excluded) estimatedShot.excluded = true;
          } else if (activeSessionRef.current) {
            estimatedShot.sessionId = activeSessionRef.current.id;
          }
        }
        if (estimatedShot) {
          const nextShots = [estimatedShot, ...shotsRef.current.filter((shot) => shot.id !== estimatedShot.id)];
          shotsRef.current = nextShots;
          setShots(nextShots);
          void syncShots(nextShots).catch(() => {});
          void uploadShotCapture(estimatedShot, event.data.image.base64, event.data.secondaryImage?.base64)
            .catch((caught) => setError(`Shot image upload failed: ${caught instanceof Error ? caught.message : 'Unknown error.'}`));
          setActiveShot(estimatedShot);
          setLiveShot(estimatedShot);
        } else {
          setActiveShot(null);
          setLiveShot(null);
        }
        // Only camera-resolved launch inputs can go to the simulator. Never send a
        // club-profile ball speed when stereo or monocular tracking failed.
        if (openGolfSimStateRef.current === 'connected' && openGolfSimAutoSendRef.current) {
          if (event.data.mode === 'full-shot') {
            if (sendCaptureToOpenGolfSim(event.data)) {
              openGolfSimSentShotIdsRef.current.add(event.data.id);
            }
          } else if (event.data.mode === 'putting' && (event.data.measurements?.metrics.launchAngleDeg?.value ?? 0) <= 10) {
            if (sendCaptureToOpenGolfSim(event.data)) openGolfSimSentShotIdsRef.current.add(event.data.id);
          }
        }
        break;
      case 'captureError':
        setError(event.data.message);
        break;
      case 'readiness': {
        const readiness = event.data;
        setStatus((current) => (current ? { ...current, readiness } : current));
        break;
      }
      case 'frameUploadProgress':
        setFrameUploadProgress((current) => ({ ...current, [event.data.captureId]: event.data }));
        if (event.data.state === 'error') setError(`Frame upload failed: ${event.data.message ?? 'Unknown error.'}`);
        break;
      case 'status':
        setStatus(event.data);
        setState(event.data.state);
        if (event.data.captureMode) {
          captureModeRef.current = event.data.captureMode;
          setCaptureMode(event.data.captureMode);
        }
        if (event.data.camera?.ballDetection) {
          setBallDetected(event.data.camera.ballDetection.state === 'detected');
        }
        break;
      case 'ballPresence':
        setBallDetected(event.data.present);
        break;
      case 'shot':
        const completedShot = normalizeShot(event.data, selectedClubRef.current);
        // The capture event arrives first and retains per-metric camera evidence.
        // The legacy shot event must not replace it with an ungraded summary.
        const displayedShot = shotsRef.current.find((shot) => shot.id === completedShot.id && shot.metricConfidence)
          ?? completedShot;
        if (!displayedShot.sessionId && activeSessionRef.current) displayedShot.sessionId = activeSessionRef.current.id;
        const nextShots = [displayedShot, ...shotsRef.current.filter((shot) => shot.id !== displayedShot.id)];
        shotsRef.current = nextShots;
        setShots(nextShots);
        void syncShots(nextShots).catch(() => {});
        setActiveShot(displayedShot);
        setLiveShot(displayedShot);
        setState('ready');
        setStatus((current) =>
          current ? { ...current, state: 'ready', lastSeenAt: new Date().toISOString() } : current,
        );
        if (
          openGolfSimStateRef.current === 'connected' &&
          openGolfSimAutoSendRef.current &&
          !openGolfSimSentShotIdsRef.current.has(displayedShot.id)
        ) {
          if (sendShotToOpenGolfSim(displayedShot)) {
            openGolfSimSentShotIdsRef.current.add(displayedShot.id);
          }
        }
        sendOpenGolfSimDeviceStatus('ready');
        break;
      case 'putt':
        const previousPutt = puttsRef.current.find((putt) => putt.id === event.data.id);
        const completedPutt: Putt = {
          ...event.data,
          number: previousPutt?.number ?? event.data.number,
          airborne: event.data.airborne ?? event.data.launchAngleDeg > 10,
          strike: event.data.strike ?? null,
        };
        const nextPutts = [completedPutt, ...puttsRef.current.filter((putt) => putt.id !== completedPutt.id)];
        puttsRef.current = nextPutts;
        setPutts(nextPutts);
        void syncPutts([completedPutt]).catch((caught) => setError(`Putt cloud sync failed: ${caught instanceof Error ? caught.message : 'Unknown error.'}`));
        setActivePutt(completedPutt);
        setState('ready');
        setStatus((current) =>
          current ? { ...current, state: 'ready', lastSeenAt: new Date().toISOString() } : current,
        );
        if (!completedPutt.airborne && openGolfSimStateRef.current === 'connected' && openGolfSimAutoSendRef.current
          && !openGolfSimSentShotIdsRef.current.has(completedPutt.id)) {
          if (sendPuttToOpenGolfSim(completedPutt)) openGolfSimSentShotIdsRef.current.add(completedPutt.id);
        }
        sendOpenGolfSimDeviceStatus('ready');
        break;
      case 'processing':
        setState('processing');
        sendOpenGolfSimDeviceStatus('busy');
        break;
      case 'preview':
        setSecondaryPreviewFrame(event.data.secondaryBase64 ? `data:${event.data.mimeType};base64,${event.data.secondaryBase64}` : null);
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
  }, [sendCaptureToOpenGolfSim, sendOpenGolfSimDeviceStatus, sendPuttToOpenGolfSim, sendShotToOpenGolfSim, syncPutts, syncShots, uploadShotCapture]);

  const setShotExcluded = useCallback((shotId: string, excluded: boolean) => {
    const update = (item: Shot) => (item.id === shotId ? { ...item, excluded } : item);
    const nextShots = shotsRef.current.map(update);
    shotsRef.current = nextShots;
    setShots(nextShots);
    setActiveShot((current) => (current ? update(current) : current));
    setLiveShot((current) => (current ? update(current) : current));
    const changed = nextShots.find((item) => item.id === shotId);
    if (changed && !isDemo) void syncShots([changed]).catch(() => {});
  }, [isDemo, syncShots]);

  /** Applies a change to one shot everywhere it is held, then syncs that shot. */
  const patchShot = useCallback((shotId: string, patch: Partial<Shot>) => {
    const update = (item: Shot) => (item.id === shotId ? { ...item, ...patch } : item);
    const nextShots = shotsRef.current.map(update);
    shotsRef.current = nextShots;
    setShots(nextShots);
    setActiveShot((current) => (current ? update(current) : current));
    setLiveShot((current) => (current ? update(current) : current));
    const changed = nextShots.find((item) => item.id === shotId);
    if (changed && !isDemo) void syncShots([changed]).catch(() => {});
  }, [isDemo, syncShots]);

  const setShotSession = useCallback((shotId: string, sessionId: string | null) => {
    patchShot(shotId, { sessionId: sessionId ?? undefined });
  }, [patchShot]);

  const setShotReference = useCallback((shotId: string, reference: ReferenceShotData | null) => {
    patchShot(shotId, { reference: reference ?? undefined });
  }, [patchShot]);

  const storeSessions = useCallback((next: PracticeSession[], active: PracticeSession | null, sync = true) => {
    sessionsRef.current = next;
    setSessions(next);
    activeSessionRef.current = active;
    setActiveSession(active);
    void AsyncStorage.setItem(SESSIONS_KEY, JSON.stringify(next));
    void (active ? AsyncStorage.setItem(ACTIVE_SESSION_KEY, active.id) : AsyncStorage.removeItem(ACTIVE_SESSION_KEY));
    if (sync && session?.user) void savePreference(SESSIONS_PREFERENCE, JSON.stringify(next)).catch(() => {});
  }, [session?.user, savePreference]);

  const startSession = useCallback((draft: { name?: string; referenceDevice?: string; notes?: string }) => {
    const now = new Date();
    const created: PracticeSession = {
      id: newSessionId(),
      name: draft.name?.trim() || defaultSessionName(now),
      startedAt: now.toISOString(),
      endedAt: null,
      ...(draft.referenceDevice?.trim() ? { referenceDevice: draft.referenceDevice.trim() } : {}),
      ...(draft.notes?.trim() ? { notes: draft.notes.trim() } : {}),
    };
    // One open session at a time: close the previous one where it stands.
    const closed = sessionsRef.current.map((item) => (item.endedAt ? item : { ...item, endedAt: created.startedAt }));
    storeSessions([created, ...closed], created);
    return created;
  }, [storeSessions]);

  const endSession = useCallback(() => {
    const active = activeSessionRef.current;
    if (!active) return;
    const endedAt = new Date().toISOString();
    storeSessions(sessionsRef.current.map((item) => (item.id === active.id ? { ...item, endedAt } : item)), null);
  }, [storeSessions]);

  const resumeSession = useCallback((sessionId: string) => {
    const target = sessionsRef.current.find((item) => item.id === sessionId);
    if (!target) return;
    const now = new Date().toISOString();
    const reopened = { ...target, endedAt: null };
    storeSessions(sessionsRef.current.map((item) => (item.id === sessionId ? reopened : item.endedAt ? item : { ...item, endedAt: now })), reopened);
  }, [storeSessions]);

  const updateSession = useCallback((updated: PracticeSession) => {
    const next = sessionsRef.current.map((item) => (item.id === updated.id ? updated : item));
    const active = activeSessionRef.current?.id === updated.id ? updated : activeSessionRef.current;
    storeSessions(next, active);
  }, [storeSessions]);

  const deleteSession = useCallback((sessionId: string) => {
    storeSessions(sessionsRef.current.filter((item) => item.id !== sessionId),
      activeSessionRef.current?.id === sessionId ? null : activeSessionRef.current);
    const orphaned = shotsRef.current.filter((shot) => shot.sessionId === sessionId);
    if (!orphaned.length) return;
    const nextShots = shotsRef.current.map((shot) => (shot.sessionId === sessionId ? { ...shot, sessionId: undefined } : shot));
    shotsRef.current = nextShots;
    setShots(nextShots);
    setActiveShot((current) => (current?.sessionId === sessionId ? { ...current, sessionId: undefined } : current));
    setLiveShot((current) => (current?.sessionId === sessionId ? { ...current, sessionId: undefined } : current));
    if (!isDemo) void syncShots(nextShots.filter((shot) => orphaned.some((item) => item.id === shot.id))).catch(() => {});
  }, [isDemo, storeSessions, syncShots]);

  // Sessions on the account are merged with this device's; a session that is open
  // here stays the active one.
  useEffect(() => {
    if (!session?.user) return;
    let cancelled = false;
    void restorePreferences().then((preferences) => {
      if (cancelled) return;
      const cloud = parseSessions(preferences[SESSIONS_PREFERENCE]);
      const local = sessionsRef.current;
      const merged = [...cloud.filter((item) => !local.some((existing) => existing.id === item.id)), ...local];
      if (merged.length !== local.length || cloud.length !== merged.length) storeSessions(merged, activeSessionRef.current);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [session?.user, restorePreferences, storeSessions]);

  const retryShotImage = useCallback(async (shot: Shot) => {
    if (!session?.user) throw new Error('Sign in to upload shot images.');
    if (!shot.captureId) throw new Error('This shot has no saved camera capture.');
    if (!client.current.connectedDeviceId) throw new Error('Connect the Pi to recover this shot image.');
    const preview = await client.current.getCaptureContactSheet(shot.captureId);
    if (preview.captureId !== shot.captureId) throw new Error('The Pi returned a different capture.');
    await uploadShotCapture(shot, preview.base64);
    const paths = await repairShotImage(shot.id);
    if (!paths.imagePath) throw new Error('The image upload finished without a Bunny path.');
    const withImage = (item: Shot) => item.id === shot.id
      ? { ...item, cloudImagePath: paths.imagePath ?? undefined, cloudSecondaryImagePath: paths.secondaryImagePath ?? undefined }
      : item;
    setShots((current) => {
      const updated = current.map(withImage);
      shotsRef.current = updated;
      return updated;
    });
    setActiveShot((current) => current ? withImage(current) : current);
    setLiveShot((current) => current ? withImage(current) : current);
    return paths.imagePath;
  }, [session?.user?.id, uploadShotCapture, repairShotImage]);

  const startShotFrameUpload = useCallback(async (shot: Shot): Promise<FrameUploadProgress> => {
    if (!session?.user) throw new Error('Sign in to upload capture frames.');
    if (!shot.captureId || !Number.isInteger(shot.frameCount) || shot.frameCount < 1) throw new Error('This shot has no saved frame sequence.');
    if (!client.current.connectedDeviceId) throw new Error('Connect the Pi to upload original frames.');
    const currentJob = await client.current.getCaptureFrameUploadStatus();
    if (currentJob?.state === 'running') {
      if (currentJob.captureId !== shot.captureId) throw new Error('The Pi is uploading another shot. Try again when it finishes.');
      setFrameUploadProgress((current) => ({ ...current, [shot.captureId!]: currentJob }));
      return currentJob;
    }
    await syncShots([shot]);
    const uploaded = new Set(await getUploadedFrameIndices(shot.id));
    const missing = Array.from({ length: shot.frameCount }, (_, index) => index).filter((index) => !uploaded.has(index));
    if (!missing.length) {
      const complete: FrameUploadProgress = { captureId: shot.captureId, uploaded: shot.frameCount, total: shot.frameCount, state: 'complete' };
      setFrameUploadProgress((current) => ({ ...current, [shot.captureId!]: complete }));
      return complete;
    }
    const ticket = await beginFrameUpload(shot.id);
    if (ticket.frameCount !== shot.frameCount) throw new Error('The cloud and Pi disagree about the frame count.');
    const started = await client.current.uploadCaptureFrames(shot.captureId, shot.frameCount, ticket.token, missing);
    setFrameUploadProgress((current) => ({ ...current, [shot.captureId!]: started }));
    return started;
  }, [session?.user?.id, syncShots, getUploadedFrameIndices, beginFrameUpload]);

  const connect = useCallback(
    async (preferredDeviceId?: string, quiet = false) => {
      clearReconnectTimer();
      intentionalDisconnect.current = false;
      setIsDemo(false);
      if (demoOriginalShots.current) {
        shotsRef.current = demoOriginalShots.current;
        setShots(demoOriginalShots.current);
        setActiveShot(demoOriginalShots.current[0] ?? null);
        demoOriginalShots.current = null;
      }
      if (demoOriginalPutts.current) {
        setPutts(demoOriginalPutts.current);
        setActivePutt(demoOriginalPutts.current[0] ?? null);
        demoOriginalPutts.current = null;
      }
      setCaptures([]);
      setPreviewFrame(null);
      setSecondaryPreviewFrame(null);
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
        if (nextStatus.state === 'ready' && nextStatus.captureMode !== 'putting') {
          nextStatus = await client.current.setClub(selectedClubRef.current, bagClubCommand(selectedBagClubRef.current));
        }
        const connectedDeviceId = client.current.connectedDeviceId;
        setDeviceId(connectedDeviceId);
        setStatus(nextStatus);
        setState(nextStatus.state);
        if (nextStatus.captureMode) {
          captureModeRef.current = nextStatus.captureMode;
          setCaptureMode(nextStatus.captureMode);
        }
        setBallDetected(nextStatus.camera?.ballDetection?.state === 'detected');
        await AsyncStorage.setItem(DEMO_KEY, 'false');
        if (connectedDeviceId) {
          await AsyncStorage.setItem(DEVICE_ID_KEY, connectedDeviceId);
        }

        // The Pi's retained history is shared by anyone who connects to it.
        // Account history comes only from this user's cloud records and live events.
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
    if (!session) return;
    let cancelled = false;
    void Promise.all([restoreShots(), restorePutts()]).then(([cloudShots, cloudPutts]) => {
      if (cancelled) return;
      const mergedShots = [...new Map([...shotsRef.current, ...cloudShots].map((shot) => [shot.id, shot])).values()]
        .sort((a, b) => b.capturedAt.localeCompare(a.capturedAt));
      const mergedPutts = [...new Map([...puttsRef.current, ...cloudPutts].map((putt) => [putt.id, putt])).values()]
        .sort((a, b) => b.capturedAt.localeCompare(a.capturedAt));
      setShots(mergedShots); shotsRef.current = mergedShots; setActiveShot(mergedShots[0] ?? null);
      setPutts(mergedPutts); setActivePutt(mergedPutts[0] ?? null);
      void syncShots(mergedShots).catch(() => {}); void syncPutts(mergedPutts).catch(() => {});
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [session, restoreShots, restorePutts, syncShots, syncPutts]);

  useEffect(() => {
    if (!session?.user || !status || isDemo || !deviceId) return;
    const camera = status.camera;
    const settings = {
      version: 1,
      deviceId,
      name: status.name,
      firmwareVersion: status.firmwareVersion,
      protocolVersion: status.protocolVersion ?? null,
      captureBackend: status.captureBackend ?? null,
      automaticCapture: status.automaticCapture ?? null,
      captureMode: status.captureMode ?? captureMode,
      selectedClubId: status.selectedClubId ?? selectedClub,
      fps: status.fps,
      exposureUs: status.exposureUs,
      gain: camera?.gain ?? null,
      autoExposure: camera?.autoExposure ?? null,
      camera: camera ? {
        model: camera.model ?? null,
        width: camera.width ?? null,
        height: camera.height ?? null,
        cameraCount: camera.cameraCount ?? null,
        primaryCameraIndex: camera.primaryCameraIndex ?? null,
        secondaryCameraIndex: camera.secondaryCameraIndex ?? null,
        secondaryExposureUs: camera.secondaryExposureUs ?? null,
        secondaryGain: camera.secondaryGain ?? null,
      } : null,
      placement: status.preview ? { roi: status.preview.roi, target: status.preview.target } : null,
      calibrationVersion: status.calibrationVersion,
      lensCalibration: status.lensCalibration ?? null,
      targetLine: status.targetLine ?? null,
    };
    const serialized = JSON.stringify(settings);
    const fingerprint = `${session.user.id}:${serialized}`;
    if (lastSavedPiSettingsRef.current === fingerprint) return;
    lastSavedPiSettingsRef.current = fingerprint;
    void savePreference(`piSettings:${deviceId}`, JSON.stringify({
      ...settings,
      savedAt: new Date().toISOString(),
    })).catch(() => {
      lastSavedPiSettingsRef.current = null;
    });
  }, [session?.user?.id, status, isDemo, deviceId, captureMode, selectedClub, savePreference]);

  useEffect(() => {
    if (!session?.user || isDemo || state !== 'ready' || !client.current.connectedDeviceId) return;
    const missing = shots.find((shot) => shot.captureId && !shot.cloudImagePath
      && Date.now() - Date.parse(shot.capturedAt) > 30_000
      && !imageRecoveryAttemptedRef.current.has(`${session.user.id}:${shot.id}`));
    if (!missing?.captureId) return;
    imageRecoveryAttemptedRef.current.add(`${session.user.id}:${missing.id}`);

    void retryShotImage(missing).catch((caught) => {
      imageRecoveryAttemptedRef.current.delete(`${session.user.id}:${missing.id}`);
      setError(`Could not recover the saved shot image: ${caught instanceof Error ? caught.message : 'Unknown error.'}`);
    });
  }, [session?.user?.id, isDemo, state, shots, retryShotImage]);

  useEffect(() => {
    if (!session?.user || isDemo || state !== 'ready' || !client.current.connectedDeviceId) return;
    if (Object.values(frameUploadProgress).some((item) => item.state === 'running')) return;
    const candidate = shots.slice(0, 3).find((shot) => shot.captureId && shot.frameCount > 0
      && !frameUploadAttemptedRef.current.has(`${session.user.id}:${shot.id}`));
    if (!candidate) return;
    frameUploadAttemptedRef.current.add(`${session.user.id}:${candidate.id}`);
    void startShotFrameUpload(candidate).catch((caught) => {
      const message = caught instanceof Error ? caught.message : 'Unknown error.';
      setError(`Frame upload failed: ${message}`);
      setFrameUploadProgress((current) => ({ ...current, [candidate.captureId!]: {
        captureId: candidate.captureId!, uploaded: 0, total: candidate.frameCount, state: 'error', message,
      } }));
    });
  }, [session?.user?.id, isDemo, state, shots, frameUploadProgress, startShotFrameUpload]);

  useEffect(() => {
    reconnect.current = connect;
  }, [connect]);

  /** Select a club type, or a named bag club of that type, and tell the Pi. */
  const applyClub = useCallback((clubId: ClubId, bagClub: BagClub | null) => {
    selectedClubRef.current = clubId;
    selectedBagClubRef.current = bagClub;
    setSelectedClub(clubId);
    setSelectedBagClub(bagClub);
    void AsyncStorage.setItem(CLUB_KEY, clubId);
    void (bagClub ? AsyncStorage.setItem(SELECTED_BAG_CLUB_KEY, bagClub.id) : AsyncStorage.removeItem(SELECTED_BAG_CLUB_KEY));
    if (client.current.connectedDeviceId) {
      void client.current.setClub(clubId, bagClubCommand(bagClub)).catch((caught) => {
        setError(caught instanceof Error ? caught.message : 'Could not update the selected club on LM1.');
      });
    }
  }, []);

  const selectClub = useCallback((clubId: ClubId) => applyClub(clubId, null), [applyClub]);

  const selectBagClub = useCallback((bagClubId: string) => {
    const club = bagClubsRef.current.find((item) => item.id === bagClubId);
    if (club) applyClub(club.baseClubId, club);
  }, [applyClub]);

  const storeBagClubs = useCallback((next: BagClub[], sync = true) => {
    bagClubsRef.current = next;
    setBagClubs(next);
    void AsyncStorage.setItem(BAG_CLUBS_KEY, JSON.stringify(next));
    if (sync && session?.user) void savePreference(BAG_CLUBS_PREFERENCE, JSON.stringify(next)).catch(() => {});
  }, [session?.user, savePreference]);

  const saveBagClub = useCallback((club: BagClub) => {
    const exists = bagClubsRef.current.some((item) => item.id === club.id);
    storeBagClubs(exists ? bagClubsRef.current.map((item) => (item.id === club.id ? club : item)) : [...bagClubsRef.current, club]);
    // Re-send an edited selected club so the Pi uses its new face size at once.
    if (selectedBagClubRef.current?.id === club.id) applyClub(club.baseClubId, club);
  }, [applyClub, storeBagClubs]);

  const deleteBagClub = useCallback((bagClubId: string) => {
    storeBagClubs(bagClubsRef.current.filter((item) => item.id !== bagClubId));
    if (selectedBagClubRef.current?.id === bagClubId) applyClub(selectedClubRef.current, null);
  }, [applyClub, storeBagClubs]);

  // The account's club list wins over a device that has none; clubs only on this
  // device are kept and pushed up.
  useEffect(() => {
    if (!session?.user) return;
    let cancelled = false;
    void restorePreferences().then((preferences) => {
      if (cancelled) return;
      const cloud = parseBagClubs(preferences[BAG_CLUBS_PREFERENCE]);
      const local = bagClubsRef.current;
      const merged = [...cloud.filter((club) => !local.some((item) => item.id === club.id)), ...local];
      if (merged.length !== local.length || cloud.length !== merged.length) storeBagClubs(merged);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [session?.user, restorePreferences, storeBagClubs]);

  const enableDemo = useCallback(() => {
    if (!demoOriginalShots.current) demoOriginalShots.current = shotsRef.current;
    if (!demoOriginalPutts.current) demoOriginalPutts.current = puttsRef.current;
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
    setSecondaryPreviewFrame(null);
    setPreviewDetection(null);
    setPreviewAprilTag(null);
    setBallDetected(false);
    void AsyncStorage.setItem(DEMO_KEY, 'true');
  }, [clearReconnectTimer]);

  useEffect(() => {
    mounted.current = true;
    const currentClient = client.current;
    void (async () => {
      const [savedDeviceId, savedDemo, savedClub, savedBagClubs, savedBagClubId, savedSessions, savedActiveSession] = await Promise.all([
        AsyncStorage.getItem(DEVICE_ID_KEY),
        AsyncStorage.getItem(DEMO_KEY),
        AsyncStorage.getItem(CLUB_KEY),
        AsyncStorage.getItem(BAG_CLUBS_KEY),
        AsyncStorage.getItem(SELECTED_BAG_CLUB_KEY),
        AsyncStorage.getItem(SESSIONS_KEY),
        AsyncStorage.getItem(ACTIVE_SESSION_KEY),
      ]);
      if (!mounted.current) return;
      if (savedDeviceId) setDeviceId(savedDeviceId);
      const restoredSessions = parseSessions(savedSessions);
      sessionsRef.current = restoredSessions;
      setSessions(restoredSessions);
      const restoredActive = restoredSessions.find((item) => item.id === savedActiveSession && !item.endedAt) ?? null;
      activeSessionRef.current = restoredActive;
      setActiveSession(restoredActive);
      const restoredBag = parseBagClubs(savedBagClubs);
      bagClubsRef.current = restoredBag;
      setBagClubs(restoredBag);
      const savedBagClub = restoredBag.find((club) => club.id === savedBagClubId);
      if (savedBagClub) selectBagClub(savedBagClub.id);
      else if (isClubId(savedClub)) selectClub(savedClub);
      if (savedDemo === 'true') enableDemo();
    })();

    return () => {
      mounted.current = false;
      clearReconnectTimer();
      if (demoTimer.current) clearTimeout(demoTimer.current);
      currentClient.disconnect();
    };
  }, [clearReconnectTimer, enableDemo, selectClub, selectBagClub]);

  const disconnect = useCallback(() => {
    intentionalDisconnect.current = true;
    clearReconnectTimer();
    client.current.disconnect();
    setIsDemo(false);
    setStatus(null);
    setState('offline');
    setError(null);
    setPreviewFrame(null);
    setSecondaryPreviewFrame(null);
    setPreviewDetection(null);
    setPreviewAprilTag(null);
    setBallDetected(false);
    void AsyncStorage.setItem(DEMO_KEY, 'false');
  }, [clearReconnectTimer]);

  const arm = useCallback(async () => {
    setError(null);
    if (captureModeRef.current !== 'full-shot' && ballDetected) {
      setError('Remove the ball before switching to normal shot mode.');
      return;
    }
    if (isDemo) {
      captureModeRef.current = 'full-shot';
      setCaptureMode('full-shot');
      setState('armed');
      setStatus((current) => (current ? { ...current, state: 'armed' } : current));
      return;
    }
    try {
      const nextStatus = await client.current.arm(selectedClub, 'full-shot', bagClubCommand(selectedBagClubRef.current));
      captureModeRef.current = 'full-shot';
      setCaptureMode('full-shot');
      setStatus(nextStatus);
      setState(nextStatus.state);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not arm the device.');
    }
  }, [ballDetected, isDemo, selectedClub]);

  const armPutting = useCallback(async () => {
    setError(null);
    if (captureModeRef.current !== 'putting' && ballDetected) {
      setError('Remove the ball before switching to putting mode.');
      return;
    }
    if (isDemo) {
      captureModeRef.current = 'putting';
      setCaptureMode('putting');
      setState('armed');
      setStatus((current) => (current ? { ...current, state: 'armed' } : current));
      return;
    }
    try {
      const nextStatus = await client.current.arm('putter', 'putting');
      captureModeRef.current = 'putting';
      setCaptureMode('putting');
      setStatus(nextStatus);
      setState(nextStatus.state);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not arm putting mode.');
    }
  }, [ballDetected, isDemo]);

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
          void syncPutts([putt]).catch(() => {});
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
          void syncShots(nextShots).catch(() => {});
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
    syncPutts,
    syncShots,
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

  const setLightMode = useCallback(async (mode: LightMode) => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to change the light.');
    try {
      const nextStatus = await client.current.setLightMode(mode);
      setStatus(nextStatus);
      setState(nextStatus.state);
      return nextStatus;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not change the light.');
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

  const captureCalibrationImage = useCallback(async (camera: CalibrationCamera = 'primary') => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to capture a lens calibration image.');
    try {
      await client.current.captureCalibrationImage(camera);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not capture the calibration image.');
      throw caught;
    }
  }, [isDemo]);

  const clearCalibrationImages = useCallback(async (camera: CalibrationCamera = 'primary') => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to clear calibration images.');
    try {
      const status = await client.current.clearCalibrationImages(camera);
      setLatestCalibrationImage(null);
      return status;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not clear the calibration images.');
      throw caught;
    }
  }, [isDemo]);

  const runLensCalibration = useCallback(async (camera: CalibrationCamera = 'primary') => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to run lens calibration.');
    try {
      return await client.current.runLensCalibration(camera);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not run lens calibration.');
      throw caught;
    }
  }, [isDemo]);

  const stereoCalibration = useCallback(async (action: StereoCalibrationAction, options: StereoCalibrationOptions = {}) => {
    if (isDemo) throw new Error('Connect to LM1 to calibrate the camera pair.');
    return client.current.stereoCalibration(action, options);
  }, [isDemo]);

  const getShotCoverage = useCallback(async () => {
    setError(null);
    if (isDemo) throw new Error('Connect to LM1 to check shot coverage.');
    try {
      return await client.current.getShotCoverage();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not check shot coverage.');
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

  const getCaptureClip = useCallback(async (captureId: string, startFrame: number, count: number) => {
    if (isDemo) throw new Error('Connect to LM1 to play the captured swing.');
    return client.current.getCaptureClip(captureId, startFrame, count);
  }, [isDemo]);

  const getCaptureFrame = useCallback(async (captureId: string, frameIndex: number) => {
    if (isDemo) throw new Error('Connect to LM1 to review capture frames.');
    return client.current.getCaptureFrame(captureId, frameIndex);
  }, [isDemo]);

  const getCaptureContactSheet = useCallback(async (captureId: string) => {
    if (isDemo) throw new Error('Connect to LM1 to review capture contact sheets.');
    return client.current.getCaptureContactSheet(captureId);
  }, [isDemo]);

  const getLatestPuttRecoveryCandidate = useCallback(async (): Promise<Putt | null> => {
    if (!session?.user) throw new Error('Sign in before saving a putt to your account.');
    if (isDemo || !client.current.connectedDeviceId) throw new Error('Connect to LM1 to find the saved putt.');
    const local = captures.filter((capture) => capture.mode === 'putting');
    const saved = await client.current.listCaptures();
    for (const capture of [...local, ...saved]) {
      if (capture.mode !== 'putting' || puttsRef.current.some((putt) => putt.id === capture.id)) continue;
      const candidate = puttFromCapture(capture, (puttsRef.current[0]?.number ?? 0) + 1);
      if (candidate) return candidate;
    }
    return null;
  }, [captures, isDemo, session?.user?.id]);

  const saveRecoveredPutt = useCallback(async (putt: Putt): Promise<void> => {
    if (!session?.user) throw new Error('Sign in before saving a putt to your account.');
    await syncPutts([putt]);
    const nextPutts = [putt, ...puttsRef.current.filter((item) => item.id !== putt.id)];
    puttsRef.current = nextPutts;
    setPutts(nextPutts);
    setActivePutt(putt);
  }, [session?.user?.id, syncPutts]);

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
      bagClubs,
      selectedBagClub,
      deviceId,
      isDemo,
      error,
      previewFrame,
      secondaryPreviewFrame,
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
      setLightMode,
      autoCalibrateExposure,
      exposureCalibration,
      clearExposureCalibration,
      resetBallCalibration,
      captureAprilTagCalibration,
      captureCalibrationImage,
      clearCalibrationImages,
      runLensCalibration,
      stereoCalibration,
      getShotCoverage,
      setTargetLine,
      clearTargetLine,
      getLatestCapturePreview,
      getCaptureFrame,
      getCaptureClip,
      getCaptureContactSheet,
      getLatestPuttRecoveryCandidate,
      saveRecoveredPutt,
      retryShotImage,
      setShotExcluded,
      sessions,
      activeSession,
      startSession,
      endSession,
      resumeSession,
      updateSession,
      deleteSession,
      setShotSession,
      setShotReference,
      frameUploadProgress,
      startShotFrameUpload,
      getWifiStatus,
      scanWifi,
      connectWifi,
      selectShot: setActiveShot,
      selectClub,
      selectBagClub,
      saveBagClub,
      deleteBagClub,
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
      bagClubs,
      selectedBagClub,
      deviceId,
      isDemo,
      error,
      previewFrame,
      secondaryPreviewFrame,
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
      setLightMode,
      autoCalibrateExposure,
      exposureCalibration,
      clearExposureCalibration,
      resetBallCalibration,
      captureAprilTagCalibration,
      captureCalibrationImage,
      clearCalibrationImages,
      runLensCalibration,
      stereoCalibration,
      getShotCoverage,
      setTargetLine,
      clearTargetLine,
      getLatestCapturePreview,
      getCaptureFrame,
      getCaptureClip,
      getCaptureContactSheet,
      getLatestPuttRecoveryCandidate,
      saveRecoveredPutt,
      retryShotImage,
      setShotExcluded,
      sessions,
      activeSession,
      startSession,
      endSession,
      resumeSession,
      updateSession,
      deleteSession,
      setShotSession,
      setShotReference,
      frameUploadProgress,
      startShotFrameUpload,
      getWifiStatus,
      scanWifi,
      connectWifi,
      selectClub,
      selectBagClub,
      saveBagClub,
      deleteBagClub,
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
