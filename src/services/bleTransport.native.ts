import { Base64 } from 'js-base64';
import {
  PermissionsAndroid,
  Platform,
  type Permission,
} from 'react-native';
import {
  BleManager,
  type Device,
  State,
  type Subscription,
} from 'react-native-ble-plx';

import {
  BleChunkHandler,
  BleConnection,
  BleDisconnectHandler,
  PINPOINT_COMMAND_UUID,
  PINPOINT_EVENT_UUID,
  PINPOINT_SERVICE_UUID,
} from '@/services/bleTransport.types';

const SCAN_TIMEOUT_MS = 12_000;
const CONNECTION_TIMEOUT_MS = 10_000;
const COMMAND_CHUNK_SIZE = 20;

let manager: BleManager | null = null;

function getManager(): BleManager {
  manager ??= new BleManager();
  return manager;
}

async function ensureAndroidPermissions(): Promise<void> {
  if (Platform.OS !== 'android') return;

  const apiLevel = Number(Platform.Version);
  const requested: Permission[] = apiLevel >= 31
    ? [
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
      ]
    : [PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION];

  const results = await PermissionsAndroid.requestMultiple(requested);
  if (requested.some((permission) => results[permission] !== PermissionsAndroid.RESULTS.GRANTED)) {
    throw new Error('Bluetooth permission is required to find the Raspberry Pi.');
  }
}

async function waitForBluetooth(activeManager: BleManager): Promise<void> {
  const currentState = await activeManager.state();
  if (currentState === State.PoweredOn) return;
  if (currentState === State.Unauthorized) {
    throw new Error('Bluetooth access is disabled for LM1 in phone settings.');
  }
  if (currentState === State.Unsupported) {
    throw new Error('This phone does not support Bluetooth Low Energy.');
  }

  await new Promise<void>((resolve, reject) => {
    let subscription: Subscription | null = null;
    const timeout = setTimeout(() => {
      subscription?.remove();
      reject(new Error('Turn on Bluetooth, then try connecting again.'));
    }, CONNECTION_TIMEOUT_MS);

    subscription = activeManager.onStateChange((nextState) => {
      if (nextState === State.PoweredOn) {
        clearTimeout(timeout);
        subscription?.remove();
        resolve();
      } else if (nextState === State.Unauthorized || nextState === State.Unsupported) {
        clearTimeout(timeout);
        subscription?.remove();
        reject(new Error('Bluetooth is not available to LM1.'));
      }
    }, true);
  });
}

async function scanForPinpoint(activeManager: BleManager): Promise<Device> {
  return new Promise<Device>((resolve, reject) => {
    let settled = false;
    const finish = (action: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      void activeManager.stopDeviceScan();
      action();
    };
    const timeout = setTimeout(() => {
      finish(() => reject(new Error('No LM1 Raspberry Pi was found nearby.')));
    }, SCAN_TIMEOUT_MS);

    void activeManager.startDeviceScan(
      [PINPOINT_SERVICE_UUID],
      { allowDuplicates: false },
      (error, device) => {
        if (error) {
          finish(() => reject(new Error(`Bluetooth scan failed: ${error.message}`)));
          return;
        }
        if (device) finish(() => resolve(device));
      },
    ).catch((error: unknown) => {
      const message = error instanceof Error ? error.message : 'Bluetooth scan could not start.';
      finish(() => reject(new Error(message)));
    });
  });
}

async function connectDevice(activeManager: BleManager, preferredDeviceId?: string): Promise<Device> {
  if (preferredDeviceId) {
    try {
      return await activeManager.connectToDevice(preferredDeviceId, { timeout: CONNECTION_TIMEOUT_MS });
    } catch {
      // The OS may forget a BLE identifier; scanning discovers the Pi again.
    }
  }
  const discovered = await scanForPinpoint(activeManager);
  return discovered.connect({ timeout: CONNECTION_TIMEOUT_MS });
}

export async function connectBle(
  preferredDeviceId: string | undefined,
  onChunk: BleChunkHandler,
  onDisconnect: BleDisconnectHandler,
): Promise<BleConnection> {
  await ensureAndroidPermissions();
  const activeManager = getManager();
  await waitForBluetooth(activeManager);

  let device = await connectDevice(activeManager, preferredDeviceId);
  if (Platform.OS === 'android') {
    try {
      device = await device.requestMTU(247);
    } catch {
      // The protocol's 20-byte chunks still work with the minimum BLE MTU.
    }
  }
  device = await device.discoverAllServicesAndCharacteristics();

  let closed = false;
  let monitorError: Error | null = null;
  let notificationSubscription: Subscription | null = null;
  let disconnectSubscription: Subscription | null = null;

  notificationSubscription = device.monitorCharacteristicForService(
    PINPOINT_SERVICE_UUID,
    PINPOINT_EVENT_UUID,
    (error, characteristic) => {
      if (closed) return;
      if (error) {
        monitorError = new Error(`Bluetooth notifications failed: ${error.message}`);
        closed = true;
        disconnectSubscription?.remove();
        onDisconnect();
        return;
      }
      if (characteristic?.value) onChunk(Base64.decode(characteristic.value));
    },
  );

  disconnectSubscription = activeManager.onDeviceDisconnected(device.id, () => {
    if (closed) return;
    closed = true;
    notificationSubscription?.remove();
    onDisconnect();
  });

  await new Promise((resolve) => setTimeout(resolve, 150));
  if (closed) {
    notificationSubscription?.remove();
    disconnectSubscription?.remove();
    void device.cancelConnection().catch(() => undefined);
    throw monitorError ?? new Error('The Raspberry Pi disconnected during Bluetooth setup.');
  }

  const mtu = Number.isFinite(device.mtu) && device.mtu >= 23 ? device.mtu : 23;
  const commandChunkSize = Math.max(COMMAND_CHUNK_SIZE, Math.min(244, mtu - 3));
  return {
    id: device.id,
    name: device.name ?? device.localName ?? 'LM1',
    mtu,
    write: async (value: string) => {
      const encodedBytes = Base64.toUint8Array(Base64.encode(value));
      for (let offset = 0; offset < encodedBytes.length; offset += commandChunkSize) {
        const chunk = encodedBytes.slice(offset, offset + commandChunkSize);
        await device.writeCharacteristicWithResponseForService(
          PINPOINT_SERVICE_UUID,
          PINPOINT_COMMAND_UUID,
          Base64.fromUint8Array(chunk),
        );
      }
    },
    disconnect: () => {
      if (closed) return;
      closed = true;
      notificationSubscription?.remove();
      disconnectSubscription?.remove();
      void device.cancelConnection().catch(() => undefined);
    },
  };
}
