export const PINPOINT_SERVICE_UUID = '7f510000-1b15-4d8d-8d9c-5f7b6a210001';
export const PINPOINT_COMMAND_UUID = '7f510001-1b15-4d8d-8d9c-5f7b6a210001';
export const PINPOINT_EVENT_UUID = '7f510002-1b15-4d8d-8d9c-5f7b6a210001';

export interface BleConnection {
  id: string;
  name: string;
  /** Negotiated ATT MTU; the Pi sizes notification chunks from it. */
  mtu?: number;
  write: (value: string) => Promise<void>;
  disconnect: () => void;
}

export type BleChunkHandler = (chunk: string) => void;
export type BleDisconnectHandler = () => void;
