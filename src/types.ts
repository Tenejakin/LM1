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

export type CaptureMode = 'full-shot' | 'putting';

export interface Putt {
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
  /** Device-measured roll distance when the camera can track the complete putt. */
  rollDistanceM?: number;
  /** Device-measured skid distance before true roll. */
  skidDistanceM?: number;
  /** True when the Pi generated this result only to verify communication. */
  simulated?: boolean;
}

export interface Shot {
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

export interface DeviceStatus {
  name: string;
  state: Exclude<DeviceState, 'offline' | 'connecting' | 'error'>;
  firmwareVersion: string;
  protocolVersion?: string;
  transport?: 'ble';
  captureBackend?: 'camera' | 'simulator';
  cameraConnected: boolean;
  fps: number;
  exposureUs: number;
  temperatureC: number;
  storageFreeGb: number;
  calibrationVersion: string;
  lastSeenAt: string;
}

export type DeviceEvent =
  | { type: 'status'; data: DeviceStatus }
  | { type: 'shot'; data: DeviceShot }
  | { type: 'putt'; data: DevicePutt }
  | { type: 'processing'; data?: { progress?: number } }
  | { type: 'ready' };

export type AppTab = 'home' | 'putting' | 'calculator' | 'history' | 'device';

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
