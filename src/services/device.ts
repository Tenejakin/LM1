import { connectBle } from '@/services/bleTransport';
import type { BleConnection } from '@/services/bleTransport.types';
import { CaptureMode, ClubId, DeviceEvent, DevicePutt, DeviceShot, DeviceStatus } from '@/types';

const REQUEST_TIMEOUT_MS = 20_000;

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
    const status = await this.request<DeviceStatus>({ type: 'status' });
    if (status.protocolVersion && !status.protocolVersion.startsWith('2.')) {
      this.disconnect();
      throw new Error(`The Raspberry Pi uses unsupported BLE protocol ${status.protocolVersion}.`);
    }
    return status;
  }

  async listShots(): Promise<DeviceShot[]> {
    return this.request<DeviceShot[]>({ type: 'listShots' });
  }

  async listPutts(): Promise<DevicePutt[]> {
    return this.request<DevicePutt[]>({ type: 'listPutts' });
  }

  async arm(clubId: ClubId | 'putter', mode: CaptureMode = 'full-shot'): Promise<DeviceStatus> {
    return this.request<DeviceStatus>({ type: 'arm', clubId, mode });
  }

  async disarm(): Promise<DeviceStatus> {
    return this.request<DeviceStatus>({ type: 'disarm' });
  }

  async trigger(): Promise<void> {
    await this.request<{ accepted: boolean }>({ type: 'trigger' });
  }

  disconnect(): void {
    this.connection?.disconnect();
    this.connection = null;
    this.onEvent = null;
    this.onDisconnect = null;
    this.messageBuffer = '';
    this.rejectPending(new Error('Bluetooth connection closed.'));
  }

  private async request<T>(command: Record<string, unknown>): Promise<T> {
    if (!this.connection) {
      throw new Error('The device is not connected.');
    }
    const id = (++this.requestCounter).toString(36);
    const response = new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('The Raspberry Pi did not respond over Bluetooth.'));
      }, REQUEST_TIMEOUT_MS);
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
      if (!message.id) return;
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
