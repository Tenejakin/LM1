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

/** model-estimate: calculated from measured values with a physics model, never observed. */
export type MetricSource = 'measured' | 'device-estimate' | 'model-estimate' | 'club-estimate';

export interface MetricCheck {
  label: string;
  passed: boolean;
}

export interface MetricConfidence {
  confidence: number;
  source: MetricSource;
  /** How the value was produced, shown in the per-metric info window. */
  reason?: string;
  /** Quality gates the device applied; every one must pass for a measured label. */
  checks?: MetricCheck[];
}

export type ShotMetricKey =
  | 'ballSpeedMps'
  | 'clubSpeedMps'
  | 'smashFactor'
  | 'launchAngleDeg'
  | 'startDirectionDeg'
  | 'strike'
  | 'attackAngleDeg'
  | 'clubPathDeg'
  | 'spinRpm'
  | 'spinAxisDeg'
  | 'estimatedCarryM';

export type CaptureMode = 'full-shot' | 'putting';

/**
 * A named club in the player's bag, e.g. two sand wedges tested side by side.
 * baseClubId is the club type the flight and spin models use.
 */
export interface BagClub {
  id: string;
  name: string;
  baseClubId: ClubId;
  /** Static loft as stamped on the club, for reference against dynamic loft. */
  loftDeg?: number | null;
  /** Heel-toe width of the face; enables strike location with faceHeightMm. */
  faceWidthMm?: number | null;
  /** Face height at the centre, leading edge to top line. */
  faceHeightMm?: number | null;
  createdAt: string;
}

/** Club values that are shown only when the camera resolved them. */
export type ClubValueKey = 'clubSpeedMps' | 'smashFactor' | 'strike' | 'attackAngleDeg' | 'clubPathDeg';

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
  strike: StrikePoint | null;
  captureId?: string;
  /** A high launch angle means a roll or pace estimate would be misleading. */
  airborne?: boolean;
  confidence: number;
  frameCount: number;
  captureDurationMs: number;
  impactFrameIndex?: number;
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
  measurementSource?: 'monocular-estimate' | 'camera-estimate';
  id: string;
  number: number;
  capturedAt: string;
  clubId: ClubId;
  /** The named bag club that hit this shot; clubId is its type. */
  bagClubId?: string;
  /** Name at the time of the shot, so history reads correctly after a rename or delete. */
  bagClubName?: string;
  ballSpeedMps: number;
  /** Null when the camera did not resolve the club; never filled from a club profile. */
  clubSpeedMps: number | null;
  /** Null unless both ball and club speed were camera-resolved. */
  smashFactor: number | null;
  launchAngleDeg: number;
  startDirectionDeg: number;
  /** Null when face contact was not measured; never assumed to be centred. */
  strike: StrikePoint | null;
  confidence: number;
  frameCount: number;
  captureDurationMs: number;
  estimatedCarryM: number;
  /** Per-value provenance so estimated numbers are never presented as measurements. */
  metricConfidence?: Partial<Record<ShotMetricKey, MetricConfidence>>;
  /** Device reason for each club value the camera could not resolve on this shot. */
  unavailableReasons?: Partial<Record<ClubValueKey, string>>;
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
  /** Club attack angle when the camera resolves it; negative is descending. */
  attackAngleDeg?: number;
  /** Horizontal club direction relative to the target line, same sign as start direction. */
  clubPathDeg?: number;
  /** Measured spin axis; positive values curve left in OpenGolfSim. */
  spinAxisDeg?: number;
  /** True when the Pi generated this result only to verify communication. */
  simulated?: boolean;
  /** Left out of session statistics by the player (a mishit or test swing); still kept in history. */
  excluded?: boolean;
  /** Private Bunny Storage image paths, populated by the signed-in user's cloud restore. */
  cloudImagePath?: string;
  cloudSecondaryImagePath?: string;
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
    shotEvidence?: {
      /** motion-only: ball measured without a club track (kept, club values unavailable). */
      status: 'club-motion-observed' | 'motion-only' | 'not-a-strike';
      clubFrames: number;
      reason: string;
    };
    tracking?: {
      status: 'failed' | 'stereo-matched' | 'stereo-two-point' | 'single-camera';
      source?: 'stereo' | 'single-camera' | null;
      speedOnly?: boolean;
      speedUncertaintyPct?: number | null;
      monoFallback?: 'used' | 'failed' | 'not-needed';
      lowerFrames: number;
      pairedFrames: number;
      pairedFrameIndices: number[];
      spanMs?: number | null;
      detection?: string | null;
      imageResidualPx?: number | null;
      failure?: string | null;
      stereoFailure?: string | null;
      monoFailure?: string | null;
      rejections?: Record<string, number> | null;
    };
    diagnostics?: {
      motionTrackedFrames?: number;
      stereo?: {
        failure?: string;
        frames?: number;
        frameIndices?: number[];
        spanMs?: number;
        detection?: string;
        rmsPx?: number;
        medianRayGapMm?: number;
        candidateRejections?: Record<string, number>;
      };
    };
    warnings?: string[];
    tagPoseFrameIndex?: number;
    tagPoseReprojectionErrorPx?: number;
    metrics: Record<string, {
      value: number | null;
      unit: string;
      status: 'estimated' | 'measured' | 'unavailable';
      reason: string;
      confidence?: number;
      checks?: MetricCheck[];
    }>;
    ballTrack3d: { frameIndex: number; positionM: number[]; centerPx?: number[] }[];
    clubTrack3d: { frameIndex: number; positionM: number[] }[];
  };
  id: string;
  captureId: string | null;
  capturedAt: string;
  clubId: string;
  /** Named bag club the Pi had selected (service 0.49.0+). */
  bagClubId?: string;
  bagClubName?: string;
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
  secondaryImage?: { mimeType: 'image/jpeg'; base64: string };
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

/** A batch of cropped lower-camera frames for the swing loop (service 0.52.0+). */
export interface CaptureClip {
  captureId: string;
  mimeType: 'image/jpeg';
  frameCount: number;
  cropBox: [number, number, number, number];
  frames: { frameIndex: number; timeMs: number | null; base64: string }[];
  impactFrameIndex: number | null;
  firstMovingFrameIndex: number | null;
  lastStationaryFrameIndex: number | null;
}

export interface CaptureFramePreview extends CapturePreview {
  secondaryBase64?: string;
  pairOffsetUs?: number;
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
  camera?: CalibrationCamera;
  /** Solved camera pose above the tag's ground plane. */
  groundPose?: { cameraHeightMm?: number; cameraPitchDeg?: number; errorPx?: number };
  /** Top-camera calibration taken from the same tag in the same moment, when two cameras stream. */
  secondary?: AprilTagCalibration;
  secondaryError?: string;
}

/** Which physical camera a calibration action applies to: primary is the lower/detection camera. */
export type CalibrationCamera = 'primary' | 'secondary';

export type StereoCalibrationAction = 'status' | 'start' | 'capture' | 'solve' | 'activate' | 'end';
export interface StereoCalibrationOptions {
  columns?: number;
  rows?: number;
  squareMm?: number;
  candidateId?: string;
}

export interface FrameUploadProgress {
  captureId: string;
  uploaded: number;
  total: number;
  state: 'running' | 'complete' | 'error';
  message?: string;
}
export interface StereoCalibrationResult {
  id: string;
  passed: boolean;
  rmsPx: number;
  validationRmsPx: number;
  validationMaxPx: number;
  baselineMm: number;
  trainingPairs: number;
  validationPairs: number;
  failures: string[];
}
export interface StereoCalibrationStatus {
  version: number;
  minimumPairs: number;
  maximumPairs: number;
  sessionId: string | null;
  board: { columns: number; rows: number; squareMm: number } | null;
  pairs: number;
  candidate: StereoCalibrationResult | null;
  active: StereoCalibrationResult | null;
}

export interface CalibrationCaptureStatus {
  camera?: CalibrationCamera;
  totalSaved: number;
  totalWithCorners: number;
  /** Per-camera counts; the top-level counts stay those of the primary camera. */
  cameras?: Record<CalibrationCamera, { camera: CalibrationCamera; totalSaved: number; totalWithCorners: number }>;
}

export interface CalibrationImageResult extends CalibrationCaptureStatus {
  index?: number;
  cornersFound?: boolean;
  columns?: number;
  rows?: number;
  image?: { mimeType: 'image/jpeg'; base64: string };
  /** Set when the device could not save the view, e.g. the second camera is not streaming. */
  error?: string;
}

export interface LensCalibrationSummary {
  rmsPx?: number;
  imageSize?: [number, number];
  views?: number;
  savedTo?: string;
}

export type ShotCoverageRating = 'good' | 'marginal' | 'insufficient';

/** One typical launch projected through the saved lens + ground pose. */
export interface ShotCoverageShot {
  id: 'putt' | 'wedge' | 'iron' | 'driver';
  label: string;
  ballSpeedMps: number;
  launchDeg: number;
  travelPerFrameMm: number;
  visiblePathMm: number;
  /** Contact falls somewhere inside a frame interval, so the count is one of these two. */
  framesMin: number;
  framesMax: number;
  pathNeededMm: number;
  rating: ShotCoverageRating;
}

/** How many frames each kind of shot gets in view at the current frame rate. Geometry only. */
export interface ShotCoverage {
  version: number;
  fps: number;
  frameIntervalMs: number;
  ballSource: 'live-ball' | 'assumed-placement';
  ballPixel: [number, number];
  ballDiameterPx: number;
  cameraToBallMm: number;
  headingSource: 'rolled-ball' | 'camera-axis';
  downrangePathMm: number;
  behindBallMm: number;
  minimumFrames: number;
  shots: ShotCoverageShot[];
  notes: string[];
  camera: CalibrationCamera;
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
  camera?: CalibrationCamera;
  rmsPx: number;
  viewsUsed: number;
  viewsTotal: number;
  imageSize: [number, number];
  savedTo: string;
}

export interface CameraDiagnostics {
  cameraCount?: number;
  primaryCameraIndex?: number;
  secondaryCameraIndex?: number;
  pairedFps?: number;
  syncMode?: 'software';
  syncReady?: boolean;
  syncOffsetUs?: number;
  secondaryFps?: number;
  secondaryExposureUs?: number;
  secondaryGain?: number;
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

export type ReadinessStatus = 'ok' | 'warn' | 'fail';

export interface ReadinessItem {
  id: 'exposure' | 'ground' | 'stereo-rest' | 'club-profile' | string;
  label: string;
  status: ReadinessStatus;
  /** What will go wrong and what to do about it. */
  detail: string;
}

export interface Readiness {
  version: 1;
  status: ReadinessStatus;
  items: ReadinessItem[];
  checkedAt: string;
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
  captureMode?: CaptureMode;
  selectedClubId?: ClubId;
  selectedBagClub?: { id: string; name: string } | null;
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
  secondaryGroundCalibration?: AprilTagCalibration | null;
  /** Pre-shot checks from the last ball placement, merged with the current club and exposure. */
  readiness?: Readiness | null;
  calibrationCapture?: CalibrationCaptureStatus;
  /** Installed lens intrinsics, keyed by camera; a missing key means that camera is uncalibrated. */
  lensCalibration?: Partial<Record<CalibrationCamera, LensCalibrationSummary>>;
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
  | { type: 'frameUploadProgress'; data: FrameUploadProgress }
  | { type: 'status'; data: DeviceStatus }
  | { type: 'ballPresence'; data: { present: boolean; confidence?: number } }
  | { type: 'shot'; data: DeviceShot }
  | { type: 'putt'; data: DevicePutt }
  | { type: 'processing'; data?: { progress?: number } }
  | { type: 'preview'; data: { mimeType: 'image/jpeg'; base64: string; secondaryBase64?: string; capturedAt: string; camera?: CameraDiagnostics } }
  | { type: 'calibrationImage'; data: CalibrationImageResult }
  | { type: 'exposureCalibration'; data: ExposureCalibrationResult }
  | { type: 'readiness'; data: Readiness }
  | { type: 'ready' };

export type AppTab = 'home' | 'putting' | 'calculator' | 'calibration' | 'history' | 'device' | 'cloud';

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
