import { CaptureAnalysis, OpenGolfSimConfig, OpenGolfSimResult, Putt, Shot } from '@/types';
import { selectSpin } from '@/utils/carry';
import { isClubId } from '@/data/clubs';

const CONNECTION_TIMEOUT_MS = 7_000;
const WEB_SOCKET_ROOT = 'wss://app.opengolfsim.com/api';
const DEFAULT_BRIDGE_PORT = 3112;

type OpenGolfSimDeviceStatus = 'ready' | 'busy';

interface OpenGolfSimHandlers {
  onDisconnect: (message: string) => void;
  onPlayerClub: (club: string | null) => void;
  onResult: (result: OpenGolfSimResult) => void;
}

interface OpenGolfSimMessage {
  type?: string;
  status?: string;
  message?: string;
  data?: {
    club?: { name?: string; id?: string };
    result?: {
      carry?: number;
      height?: number;
      roll?: number;
      total?: number;
      lateral?: number;
    };
  };
}

export function openGolfSimSocketUrl(config: OpenGolfSimConfig): string {
  if (config.mode === 'web') {
    const email = config.accountEmail.trim().toLowerCase();
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      throw new Error('Enter the email address used for your OpenGolfSim account.');
    }
    return `${WEB_SOCKET_ROOT}/${encodeURIComponent(email)}`;
  }

  const value = config.bridgeAddress.trim().replace(/\/+$/, '');
  if (!value) {
    throw new Error('Enter the desktop bridge address.');
  }

  const withProtocol = /^https?:\/\//i.test(value)
    ? value.replace(/^http/i, 'ws')
    : /^wss?:\/\//i.test(value)
      ? value
      : `ws://${value}`;
  try {
    const url = new URL(withProtocol);
    if (url.protocol !== 'ws:' && url.protocol !== 'wss:') {
      throw new Error('unsupported protocol');
    }
    if (!url.port) url.port = String(DEFAULT_BRIDGE_PORT);
    return url.toString().replace(/\/$/, '');
  } catch {
    throw new Error('Use a bridge address such as 192.168.1.50:3112.');
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function fallbackSpinRpm(shot: Shot): number {
  return selectSpin(shot.clubId, shot.ballSpeedMps, shot.launchAngleDeg, null, shot.clubSpeedMps, shot.attackAngleDeg).rpm;
}

export function toOpenGolfSimShot(shot: Shot) {
  return {
    type: 'shot' as const,
    unit: 'metric' as const,
    shot: {
      ballSpeed: Number(Math.max(0, shot.ballSpeedMps).toFixed(3)),
      verticalLaunchAngle: Number(clamp(shot.launchAngleDeg, 0, 45).toFixed(2)),
      horizontalLaunchAngle: Number(clamp(shot.startDirectionDeg, -45, 45).toFixed(2)),
      spinSpeed: Math.round(Math.max(0, shot.spinRpm ?? fallbackSpinRpm(shot))),
      spinAxis: Number(clamp(shot.spinAxisDeg ?? 0, -45, 45).toFixed(2)),
    },
  };
}

export function toOpenGolfSimPutt(putt: Putt) {
  const rollingSpinRpm = putt.ballSpeedMps / (2 * Math.PI * 0.02135) * 60;
  return {
    type: 'shot' as const,
    unit: 'metric' as const,
    shot: {
      ballSpeed: Number(Math.max(0, putt.ballSpeedMps).toFixed(3)),
      verticalLaunchAngle: Number(clamp(putt.launchAngleDeg, 0, 10).toFixed(2)),
      horizontalLaunchAngle: Number(clamp(putt.launchDirectionDeg, -45, 45).toFixed(2)),
      spinSpeed: Math.round(Math.max(0, rollingSpinRpm)),
      spinAxis: 0,
    },
  };
}

/**
 * A camera hit carries only what the pipeline resolved. The simulator needs ball speed
 * and both launch angles; spin is filled the same way complete shots already are
 * (club-based fallback, or rolling spin for a putt). Returns null when any of the
 * three measured values is missing rather than inventing one.
 */
export function toOpenGolfSimCapture(capture: CaptureAnalysis) {
  if (capture.classification !== 'motion-observed'
      || (capture.mode === 'full-shot' && capture.measurements?.shotEvidence?.status === 'not-a-strike')) return null;
  const metrics = capture.measurements?.metrics;
  const speed = metrics?.ballSpeedMps?.value;
  const launch = metrics?.launchAngleDeg?.value;
  const direction = metrics?.startDirectionDeg?.value;
  if (speed === null || speed === undefined || launch === null || launch === undefined || direction === null || direction === undefined) {
    return null;
  }
  if (![speed, launch, direction].every(Number.isFinite) || speed <= 0) return null;
  if (capture.mode === 'putting') {
    const rollingSpinRpm = speed / (2 * Math.PI * 0.02135) * 60;
    return {
      type: 'shot' as const,
      unit: 'metric' as const,
      shot: {
        ballSpeed: Number(Math.max(0, speed).toFixed(3)),
        verticalLaunchAngle: Number(clamp(launch, 0, 10).toFixed(2)),
        horizontalLaunchAngle: Number(clamp(direction, -45, 45).toFixed(2)),
        spinSpeed: Math.round(Math.max(0, rollingSpinRpm)),
        spinAxis: 0,
      },
    };
  }
  const clubId = isClubId(capture.clubId) ? capture.clubId : 'driver';
  const measuredSpin = metrics?.spinRpm?.value;
  const measuredAxis = metrics?.spinAxisDeg?.value;
  return {
    type: 'shot' as const,
    unit: 'metric' as const,
    shot: {
      ballSpeed: Number(Math.max(0, speed).toFixed(3)),
      verticalLaunchAngle: Number(clamp(launch, 0, 45).toFixed(2)),
      horizontalLaunchAngle: Number(clamp(direction, -45, 45).toFixed(2)),
      spinSpeed: Math.round(Math.max(0, selectSpin(clubId, speed, launch, measuredSpin,
        metrics?.clubSpeedMps?.value, metrics?.attackAngleDeg?.value).rpm)),
      spinAxis: Number(clamp(measuredAxis ?? 0, -45, 45).toFixed(2)),
    },
  };
}

function parseResult(message: OpenGolfSimMessage): OpenGolfSimResult | null {
  const result = message.data?.result;
  if (!result || typeof result.carry !== 'number' || typeof result.total !== 'number') {
    return null;
  }

  return {
    carryM: result.carry,
    heightM: result.height ?? 0,
    rollM: result.roll ?? 0,
    totalM: result.total,
    lateralM: result.lateral ?? 0,
  };
}

export class OpenGolfSimClient {
  private socket: WebSocket | null = null;
  private connected = false;

  async connect(config: OpenGolfSimConfig, handlers: OpenGolfSimHandlers): Promise<void> {
    this.disconnect();
    const url = openGolfSimSocketUrl(config);
    const socket = new WebSocket(url);
    this.socket = socket;

    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const timeout = setTimeout(() => {
        fail('OpenGolfSim did not respond within 7 seconds.');
      }, CONNECTION_TIMEOUT_MS);

      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        this.connected = true;
        resolve();
      };

      const fail = (message: string) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        socket.onclose = null;
        socket.close();
        if (this.socket === socket) this.socket = null;
        reject(new Error(message));
      };

      socket.onopen = () => {
        if (config.mode === 'web') finish();
      };

      socket.onerror = () => {
        fail(
          config.mode === 'desktop'
            ? 'Could not reach the desktop bridge. Check its address and firewall.'
            : 'Could not connect to OpenGolfSim Web. Check the account email and network.',
        );
      };

      socket.onmessage = ({ data }) => {
        let message: OpenGolfSimMessage;
        try {
          message = JSON.parse(String(data)) as OpenGolfSimMessage;
        } catch {
          return;
        }

        if (message.type === 'bridge') {
          if (message.status === 'connected') finish();
          if (message.status === 'error') fail(message.message ?? 'The bridge could not reach OpenGolfSim Desktop.');
          return;
        }

        if (message.type === 'player') {
          handlers.onPlayerClub(message.data?.club?.name ?? message.data?.club?.id ?? null);
        }

        if (message.type === 'result') {
          const result = parseResult(message);
          if (result) handlers.onResult(result);
        }
      };

      socket.onclose = () => {
        const wasConnected = this.connected;
        this.connected = false;
        if (this.socket === socket) this.socket = null;
        if (!settled) {
          fail('The OpenGolfSim connection closed before it was ready.');
        } else if (wasConnected) {
          handlers.onDisconnect('OpenGolfSim disconnected.');
        }
      };
    });

    this.sendDeviceStatus('ready');
  }

  sendDeviceStatus(status: OpenGolfSimDeviceStatus): void {
    this.send({ type: 'device', status });
  }

  sendShot(shot: Shot): void {
    this.send(toOpenGolfSimShot(shot));
  }

  sendPutt(putt: Putt): void {
    this.send(toOpenGolfSimPutt(putt));
  }

  /** Returns false when the capture lacks speed, launch or direction; nothing is sent. */
  sendCapture(capture: CaptureAnalysis): boolean {
    const payload = toOpenGolfSimCapture(capture);
    if (!payload) return false;
    this.send(payload);
    return true;
  }

  sendTestShot(): void {
    this.send({
      type: 'shot',
      unit: 'metric',
      shot: {
        ballSpeed: 44.704,
        verticalLaunchAngle: 15.4,
        horizontalLaunchAngle: -2.1,
        spinSpeed: 3021,
        spinAxis: -0.5,
      },
    });
  }

  disconnect(): void {
    this.connected = false;
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
  }

  private send(payload: object): void {
    if (!this.connected || !this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error('Connect OpenGolfSim before sending shot data.');
    }
    this.socket.send(JSON.stringify(payload));
  }
}
