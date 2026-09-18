import {
  BleChunkHandler,
  BleConnection,
  BleDisconnectHandler,
} from '@/services/bleTransport.types';

export async function connectBle(
  _preferredDeviceId: string | undefined,
  _onChunk: BleChunkHandler,
  _onDisconnect: BleDisconnectHandler,
): Promise<BleConnection> {
  throw new Error('Raspberry Pi connections require the LM1 iOS or Android app. Web preview supports demo mode only.');
}
