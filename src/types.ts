export type DeviceState =
  | 'offline'
  | 'connecting'
  | 'ready'
  | 'armed'
  | 'processing'
  | 'error';

export type ClubId =
  | 'driver'
  | '3-wood'
  | '5-wood'
  | '3-hybrid'
  | '4-hybrid'
  | '4-iron'
  | '5-iron'
  | '6-iron'
  | '7-iron'
  | '8-iron'
  | '9-iron'
  | 'pitching-wedge'
  | 'gap-wedge'
  | 'sand-wedge'
  | 'lob-wedge';

export interface StrikePoint {
  /** Positive values are toward the toe. */
  xMm: number;
  /** Positive values are above the face center. */
  yMm: number;
}

export type MetricSource = 'measured' | 'device-estimate' | 'club-estimate';

export interface MetricConfidence {
  confidence: number;
  source: MetricSource;
}

export type ShotMetricKey =
  | 'ballSpeedMps'
  | 'clubSpeedMps'
  | 'smashFactor'
  | 'launchAngleDeg'
  | 'startDirectionDeg'
  | 'strike'
  | 'spinRpm'
  | 'spinAxisDeg'
  | 'estimatedCarryM';

export type CaptureMode = 'full-shot' | 'putting';

export interface Putt {
  measurementSource?: 'monocular-estimate';
  id: string;
  number: number;
  capturedAt: string;
  ballSpeedMps: number;
  putterSpeedMps: number;
  smashFactor: number;
  launchDirectionDeg: number;
  launchAngleDeg: number;
  strike: StrikePoint;
  confidence: number;
  frameCount: number;
  captureDurationMs: number;
  /** Sampled/debounced disappearance trigger; diagnostic only, not impact. */
  coarseDepartureFrameIndex?: number;
  /** Last frame where the armed ball still matches its resting position. */
  lastStationaryFrameIndex?: number;
  /** First frame in a consistent outgoing-ball sequence. */
  firstMovingFrameIndex?: number;
  /** Device-measured roll distance when the camera can track the complete putt. */
  rollDistanceM?: number;
  /** Device-measured skid distance before true roll. */
  skidDistanceM?: number;
  /** True when the Pi generated this result only to verify communication. */
  simulated?: boolean;
}

export interface Shot {
  measurementSource?: 'monocular-estimate';
  id: string;
  number: number;
  capturedAt: string;
  clubId: ClubId;
  ballSpeedMps: number;
  clubSpeedMps: number;
  smashFactor: number;
  launchAngleDeg: number;
  startDirectionDeg: number;
  strike: StrikePoint;
  confidence: number;
  frameCount: number;
  captureDurationMs: number;
  estimatedCarryM: number;
  /** Per-value provenance so estimated numbers are never presented as measurements. */
  metricConfidence?: Partial<Record<ShotMetricKey, MetricConfidence>>;
  /** Exact rolling burst retained on the Pi for frame-by-frame review. */
  captureId?: string;
  /** Backward-compatible best event frame; first motion when resolved, otherwise the coarse trigger. */
  impactFrameIndex?: number;
  /** Sampled/debounced disappearance trigger; diagnostic only, not impact. */
  coarseDepartureFrameIndex?: number;
  /** Last frame where the armed ball still matches its resting position. */
  lastStationaryFrameIndex?: number;
  /** First frame in a consistent outgoing-ball sequence. */
  firstMovingFrameIndex?: number;
  /** Measured backspin when the device provides it. */
  spinRpm?: number;
  /** Measured spin axis; positive values curve left in OpenGolfSim. */
  spinAxisDeg?: number;
  /** True when the Pi generated this result only to verify communication. */
  simulated?: boolean;
}

export type DeviceShot = Omit<Shot, 'clubId' | 'estimatedCarryM'> & {
  clubId?: ClubId;
  estimatedCarryM?: number;
};

export type DevicePutt = Putt;

export interface CaptureAnalysis {
  measurements?: {
    method: string;
    failure?: string;
    warnings?: string[];
    tagPoseFrameIndex?: number;
    tagPoseReprojectionErrorPx?: number;
    metrics: Record<string, { value: number | null; unit: string; status: 'estimated' | 'measured' | 'unavailable'; reason: string }>;
    ballTrack3d: { frameIndex: number; positionM: number[]; centerPx?: number[] }[];
    clubTrack3d: { frameIndex: number; positionM: number[] }[];
  };
  id: string;
  captureId: string | null;
  capturedAt: string;
  clubId: string;
  mode: CaptureMode;
  classification: 'motion-observed' | 'unconfirmed-departure';
  frameCount: number;
  captureDurationMs: number;
  measuredFps: number | null;
  impactFrameIndex: number;
  coarseDepartureFrameIndex: number;
  lastStationaryFrameIndex: number | null;
  firstMovingFrameIndex: number | null;
  imageFrameIndex: number;
  warnings: string[];
  image: { mimeType: 'image/jpeg'; base64: string };
  track: { frameIndex: number; x: number; y: number; score: number }[];
}

export interface BallDetection {
  state: 'calibrating' | 'detected' | 'waiting' | 'disabled';
  /** Normalized left, top, width, height in the accompanying preview. */
  bounds: [number, number, number, number] | null;
  /** Largest foreground blob of the last detector sample, accepted or not, for diagnosing a marginal ball. */
  candidate?: {
    area: number;
    circularity: number;
    aspect: number;
    bounds: [number, number, number, number];
    rejected: 'area' | 'circularity' | 'aspect' | null;
  } | null;
}

export interface CapturePreview {
  mimeType: 'image/jpeg';
  base64: string;
  captureId: string;
}

export interface CaptureFramePreview extends CapturePreview {
  frameIndex: number;
  frameCount: number;
  timeMs: number | null;
  impactFrameIndex: number | null;
  coarseDepartureFrameIndex: number | null;
  lastStationaryFrameIndex: number | null;
  firstMovingFrameIndex: number | null;
}

export interface AprilTagCalibration {
  detected: boolean;
  available: boolean;
  family: 'tag36h11';
  tagId: number;
  tagSizeMm?: number;
  imageSize?: [number, number];
  /** Normalized clockwise corners in the camera frame. */
  corners?: [[number, number], [number, number], [number, number], [number, number]];
  center?: [number, number];
  edgePixels?: number;
  pixelsPerMm?: number;
  rotationDeg?: number;
  perspectiveError?: number;
  quality?: number;
  imageToTagMm?: number[][];
  distanceMm?: number;
  capturedAt?: string;
  version?: number;
  message?: string;
}

export interface CalibrationCaptureStatus {
  totalSaved: number;
  totalWithCorners: number;
}

export interface CalibrationImageResult extends CalibrationCaptureStatus {
  index: number;
  cornersFound: boolean;
  columns: number;
  rows: number;
  image: { mimeType: 'image/jpeg'; base64: string };
}

export interface TargetLine {
  version: number;
  /** Degrees from the ground tag's +X axis toward +Y; start direction is measured against this line. */
  headingDeg: number;
  points: number;
  displacementM: number;
  capturedAt: string;
}

export interface LensCalibrationResult {
  rmsPx: number;
  viewsUsed: number;
  viewsTotal: number;
  imageSize: [number, number];
  savedTo: string;
}

export interface CameraDiagnostics {
  ballDetection?: BallDetection;
  aprilTag?: AprilTagCalibration;
  model?: string;
  width?: number;
  height?: number;
  fps?: number;
  exposureUs?: number;
  gain?: number;
  autoExposure?: boolean;
  autofocus?: boolean;
  /** Relative sharpness within the placement area; compare only the same scene. */
  focusScore?: number;
}

export interface DeviceStatus {
  automaticCapture?: boolean;
  name: string;
  state: Exclude<DeviceState, 'offline' | 'connecting' | 'error'>;
  firmwareVersion: string;
  protocolVersion?: string;
  transport?: 'ble';
  wifiProvisioning?: boolean;
  captureBackend?: 'camera' | 'simulator';
  selectedClubId?: ClubId;
  cameraConnected: boolean;
  camera?: CameraDiagnostics;
  fps: number;
  exposureUs: number;
  exposureControl?: {
    configurable: boolean;
    minUs: number;
    maxUs: number;
    stepUs: number;
  };
  gainControl?: {
    configurable: boolean;
    min: number;
    max: number;
    step: number;
  };
  temperatureC: number;
  storageFreeGb: number;
  calibrationVersion: string;
  groundCalibration?: AprilTagCalibration | null;
  calibrationCapture?: CalibrationCaptureStatus;
  targetLine?: TargetLine | null;
  lastSeenAt: string;
  preview?: {
    transport: 'ble';
    intervalMs: number;
    width: number;
    height: number;
    roi: [number, number, number, number];
    target: [number, number];
  };
}

export interface WifiNetwork {
  ssid: string;
  signal: number;
  security: string;
  secure: boolean;
  supported: boolean;
  connected: boolean;
}

export interface WifiConnectionStatus {
  available: boolean;
  connected: boolean;
  interface: string;
  ssid?: string;
  signal?: number;
  ipAddress?: string;
}

/** What an automatic exposure sweep settled on, and how the frame looked there. */
export interface ExposureCalibrationResult {
  ok: boolean;
  error?: string;
  exposureUs?: number;
  gain?: number;
  meanBrightness?: number;
  clippedFraction?: number;
  usable?: boolean;
  samplesTaken?: number;
  note?: string;
}

export type DeviceEvent =
  | { type: 'capture'; data: CaptureAnalysis }
  | { type: 'captureError'; data: { message: string } }
  | { type: 'status'; data: DeviceStatus }
  | { type: 'ballPresence'; data: { present: boolean; confidence?: number } }
  | { type: 'shot'; data: DeviceShot }
  | { type: 'putt'; data: DevicePutt }
  | { type: 'processing'; data?: { progress?: number } }
  | { type: 'preview'; data: { mimeType: 'image/jpeg'; base64: string; capturedAt: string; camera?: CameraDiagnostics } }
  | { type: 'calibrationImage'; data: CalibrationImageResult }
  | { type: 'exposureCalibration'; data: ExposureCalibrationResult }
  | { type: 'ready' };

export type AppTab = 'home' | 'putting' | 'calculator' | 'calibration' | 'history' | 'device';

export type OpenGolfSimMode = 'web' | 'desktop';

export type OpenGolfSimState = 'offline' | 'connecting' | 'connected' | 'error';

export interface OpenGolfSimConfig {
  mode: OpenGolfSimMode;
  accountEmail: string;
  bridgeAddress: string;
  autoSend: boolean;
}

export interface OpenGolfSimResult {
  carryM: number;
  heightM: number;
  rollM: number;
  totalM: number;
  lateralM: number;
}

export interface N8nConfig {
  webhookUrl: string;
}

export type N8nSendState = 'idle' | 'sending' | 'sent' | 'error';

export interface N8nShotPayload {
  event: 'lm1.shot';
  schemaVersion: 1;
  sentAt: string;
  source: {
    app: 'LM1';
    appVersion: string;
  };
  shot: Shot;
}

export interface N8nCapturePayload {
  event: 'lm1.capture';
  schemaVersion: 1;
  sentAt: string;
  source: {
    app: 'LM1';
    appVersion: string;
  };
  capture: CaptureAnalysis;
}
