import { connectBle } from '@/services/bleTransport';
import type { BleConnection } from '@/services/bleTransport.types';
import {
  AprilTagCalibration,
  CalibrationCamera,
  CalibrationCaptureStatus,
  CaptureAnalysis,
  CaptureMode,
  CaptureFramePreview,
  FrameUploadProgress,
  CapturePreview,
  ClubId,
  DeviceEvent,
  DevicePutt,
  DeviceShot,
  DeviceStatus,
  LensCalibrationResult,
  StereoCalibrationAction,
  StereoCalibrationOptions,
  StereoCalibrationStatus,
  ShotCoverage,
  TargetLine,
  WifiConnectionStatus,
  WifiNetwork,
} from '@/types';

const REQUEST_TIMEOUT_MS = 20_000;
const WIFI_CONNECT_TIMEOUT_MS = 50_000;

export type BagClubCommand = { id: string; name: string; faceWidthMm?: number; faceHeightMm?: number };

type WireResponse = { type: 'response'; id: string; data: unknown };
type WireError = { type: 'error'; id?: string; message: string };
type WireMessage = DeviceEvent | WireResponse | WireError;

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timeout: ReturnType<typeof setTimeout>;
}

export class DeviceClient {
  private connection: BleConnection | null = null;
  private messageBuffer = '';
  private requestCounter = 0;
  private pending = new Map<string, PendingRequest>();
  private onEvent: ((event: DeviceEvent) => void) | null = null;
  private onDisconnect: (() => void) | null = null;

  get connectedDeviceId(): string | null {
    return this.connection?.id ?? null;
  }

  async connect(
    preferredDeviceId: string | undefined,
    onEvent: (event: DeviceEvent) => void,
    onDisconnect: () => void,
  ): Promise<DeviceStatus> {
    this.disconnect();
    this.onEvent = onEvent;
    this.onDisconnect = onDisconnect;
    this.connection = await connectBle(
      preferredDeviceId,
      (chunk) => this.receiveChunk(chunk),
      () => this.handleDisconnect(),
    );
    const status = await this.request<DeviceStatus>({ type: 'status', mtu: this.connection.mtu });
    if (status.protocolVersion && !status.protocolVersion.startsWith('2.')) {
      this.disconnect();
      throw new Error(`The Raspberry Pi uses unsupported BLE protocol ${status.protocolVersion}.`);
    }
    return status;
  }

  async listShots(): Promise<DeviceShot[]> {
    return this.request<DeviceShot[]>({ type: 'listShots' });
  }

  async listCaptures(): Promise<CaptureAnalysis[]> {
    return this.request<CaptureAnalysis[]>({ type: 'listCaptures' }, 60_000);
  }

  async listPutts(): Promise<DevicePutt[]> {
    return this.request<DevicePutt[]>({ type: 'listPutts' });
  }

  async arm(clubId: ClubId | 'putter', mode: CaptureMode = 'full-shot', bagClub?: BagClubCommand): Promise<DeviceStatus> {
    return this.request<DeviceStatus>({ type: 'arm', clubId, mode, ...(bagClub ? { bagClub } : {}) });
  }

  /** A named bag club rides along so the Pi can label captures and load its face size. */
  async setClub(clubId: ClubId, bagClub?: BagClubCommand): Promise<DeviceStatus> {
    return this.request<DeviceStatus>({ type: 'setClub', clubId, ...(bagClub ? { bagClub } : {}) });
  }

  async disarm(): Promise<DeviceStatus> {
    return this.request<DeviceStatus>({ type: 'disarm' });
  }

  async trigger(): Promise<void> {
    await this.request<{ accepted: boolean }>({ type: 'trigger' });
  }

  async resetBallCalibration(): Promise<void> {
    await this.request<{ accepted: boolean }>({ type: 'resetBallCalibration' });
  }

  async setExposure(exposureUs: number): Promise<DeviceStatus> {
    return this.request<DeviceStatus>({ type: 'setExposure', exposureUs });
  }

  async setGain(gain: number): Promise<DeviceStatus> {
    return this.request<DeviceStatus>({ type: 'setGain', gain });
  }

  /**
   * Ask LM1 to work out exposure and gain for the light it is standing in. The
   * sweep runs on the device; the chosen values arrive as an exposureCalibration
   * event, so this only confirms the request was accepted.
   */
  async autoCalibrateExposure(): Promise<void> {
    await this.request<{ accepted: boolean }>({ type: 'autoCalibrateExposure' }, 30_000);
  }

  async captureAprilTagCalibration(): Promise<AprilTagCalibration> {
    return this.request<AprilTagCalibration>({ type: 'captureAprilTagCalibration' }, 30_000);
  }

  async captureCalibrationImage(camera: CalibrationCamera = 'primary'): Promise<void> {
    await this.request<{ accepted: boolean }>({ type: 'captureCalibrationImage', camera });
  }

  async clearCalibrationImages(camera: CalibrationCamera = 'primary'): Promise<CalibrationCaptureStatus> {
    return this.request<CalibrationCaptureStatus>({ type: 'clearCalibrationImages', camera });
  }

  async stereoCalibration(action: StereoCalibrationAction, options: StereoCalibrationOptions = {}): Promise<StereoCalibrationStatus> {
    return this.request<StereoCalibrationStatus>({ type: 'stereoCalibration', action, ...options }, 120_000);
  }

  async runLensCalibration(camera: CalibrationCamera = 'primary'): Promise<LensCalibrationResult> {
    return this.request<LensCalibrationResult>({ type: 'runLensCalibration', camera }, 30_000);
  }

  async getShotCoverage(): Promise<ShotCoverage> {
    return this.request<ShotCoverage>({ type: 'shotCoverage' }, 15_000);
  }

  async setTargetLine(): Promise<TargetLine> {
    return this.request<TargetLine>({ type: 'setTargetLine' });
  }

  async clearTargetLine(): Promise<void> {
    await this.request<{ cleared: boolean }>({ type: 'clearTargetLine' });
  }

  async getLatestCapturePreview(): Promise<CapturePreview> {
    return this.request<CapturePreview>({ type: 'latestCapturePreview' }, 45_000);
  }

  async getCaptureFrame(captureId: string, frameIndex: number): Promise<CaptureFramePreview> {
    return this.request<CaptureFramePreview>(
      { type: 'captureFrame', captureId, frameIndex },
      30_000,
    );
  }

  async getCaptureContactSheet(captureId: string): Promise<CapturePreview> {
    return this.request<CapturePreview>({ type: 'captureContactSheet', captureId }, 45_000);
  }

  async uploadCaptureFrames(captureId: string, frameCount: number, ticket: string, indices: number[]): Promise<FrameUploadProgress> {
    return this.request<FrameUploadProgress>({ type: 'uploadCaptureFrames', captureId, frameCount, ticket, indices }, 45_000);
  }

  async getCaptureFrameUploadStatus(): Promise<FrameUploadProgress | null> {
    return this.request<FrameUploadProgress | null>({ type: 'captureFrameUploadStatus' });
  }

  async getWifiStatus(): Promise<WifiConnectionStatus> {
    return this.request<WifiConnectionStatus>({ type: 'wifiStatus' });
  }

  async scanWifi(): Promise<WifiNetwork[]> {
    return this.request<WifiNetwork[]>({ type: 'wifiScan' });
  }

  async connectWifi(
    ssid: string,
    password: string,
    hidden = false,
  ): Promise<WifiConnectionStatus> {
    return this.request<WifiConnectionStatus>(
      { type: 'wifiConnect', ssid, password, hidden },
      WIFI_CONNECT_TIMEOUT_MS,
    );
  }

  disconnect(): void {
    this.connection?.disconnect();
    this.connection = null;
    this.onEvent = null;
    this.onDisconnect = null;
    this.messageBuffer = '';
    this.rejectPending(new Error('Bluetooth connection closed.'));
  }

  private async request<T>(
    command: Record<string, unknown>,
    timeoutMs = REQUEST_TIMEOUT_MS,
  ): Promise<T> {
    if (!this.connection) {
      throw new Error('The device is not connected.');
    }
    const id = (++this.requestCounter).toString(36);
    const response = new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('The Raspberry Pi did not respond over Bluetooth.'));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        timeout,
      });
    });

    try {
      await this.connection.write(`${JSON.stringify({ id, ...command })}\n`);
    } catch (error) {
      const pending = this.pending.get(id);
      if (pending) {
        clearTimeout(pending.timeout);
        this.pending.delete(id);
        pending.reject(error instanceof Error ? error : new Error('Bluetooth write failed.'));
      }
    }
    return response;
  }

  private receiveChunk(chunk: string): void {
    this.messageBuffer += chunk;
    if (this.messageBuffer.length > 128_000) {
      this.messageBuffer = '';
      this.rejectPending(new Error('The Raspberry Pi sent an oversized Bluetooth message.'));
      return;
    }

    while (this.messageBuffer.includes('\n')) {
      const newline = this.messageBuffer.indexOf('\n');
      const rawMessage = this.messageBuffer.slice(0, newline);
      this.messageBuffer = this.messageBuffer.slice(newline + 1);
      if (!rawMessage) continue;
      try {
        this.handleMessage(JSON.parse(rawMessage) as WireMessage);
      } catch {
        // A malformed packet is isolated so later BLE messages can continue.
      }
    }
  }

  private handleMessage(message: WireMessage): void {
    if (message.type === 'response') {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timeout);
      this.pending.delete(message.id);
      pending.resolve(message.data);
      return;
    }
    if (message.type === 'error') {
      if (!message.id) {
        this.onEvent?.({ type: 'captureError', data: { message: message.message } });
        return;
      }
      const pending = this.pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timeout);
      this.pending.delete(message.id);
      pending.reject(new Error(message.message));
      return;
    }
    this.onEvent?.(message);
  }

  private handleDisconnect(): void {
    if (!this.connection) return;
    this.connection = null;
    this.messageBuffer = '';
    this.rejectPending(new Error('Bluetooth connection lost.'));
    this.onDisconnect?.();
  }

  private rejectPending(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pending.clear();
  }
}
