import { getClub } from '@/data/clubs';
import { ClubId, DeviceStatus, Shot } from '@/types';
import { estimateCarryMeters } from '@/utils/carry';

const now = Date.now();

function withEstimatedCarry(shot: Omit<Shot, 'estimatedCarryM'>): Shot {
  return { ...shot, estimatedCarryM: estimateCarryMeters(shot) };
}

export const demoShots: Shot[] = [
  withEstimatedCarry({
    id: 'demo-27',
    number: 27,
    capturedAt: new Date(now - 2 * 60 * 1000).toISOString(),
    clubId: 'driver',
    ballSpeedMps: 61.8,
    clubSpeedMps: 42.4,
    smashFactor: 1.46,
    launchAngleDeg: 14.2,
    startDirectionDeg: 1.8,
    strike: { xMm: 7, yMm: 2 },
    confidence: 0.96,
    frameCount: 186,
    captureDurationMs: 602,
  }),
  withEstimatedCarry({
    id: 'demo-26',
    number: 26,
    capturedAt: new Date(now - 6 * 60 * 1000).toISOString(),
    clubId: 'driver',
    ballSpeedMps: 59.6,
    clubSpeedMps: 41.8,
    smashFactor: 1.43,
    launchAngleDeg: 13.7,
    startDirectionDeg: -0.8,
    strike: { xMm: 2, yMm: -3 },
    confidence: 0.94,
    frameCount: 184,
    captureDurationMs: 596,
  }),
  withEstimatedCarry({
    id: 'demo-25',
    number: 25,
    capturedAt: new Date(now - 10 * 60 * 1000).toISOString(),
    clubId: '3-wood',
    ballSpeedMps: 63.1,
    clubSpeedMps: 42.7,
    smashFactor: 1.48,
    launchAngleDeg: 15.1,
    startDirectionDeg: 2.6,
    strike: { xMm: 4, yMm: 4 },
    confidence: 0.97,
    frameCount: 187,
    captureDurationMs: 605,
  }),
  withEstimatedCarry({
    id: 'demo-24',
    number: 24,
    capturedAt: new Date(now - 15 * 60 * 1000).toISOString(),
    clubId: 'driver',
    ballSpeedMps: 57.9,
    clubSpeedMps: 41.2,
    smashFactor: 1.41,
    launchAngleDeg: 12.9,
    startDirectionDeg: -2.1,
    strike: { xMm: -6, yMm: -2 },
    confidence: 0.91,
    frameCount: 182,
    captureDurationMs: 589,
  }),
  withEstimatedCarry({
    id: 'demo-23',
    number: 23,
    capturedAt: new Date(now - 21 * 60 * 1000).toISOString(),
    clubId: 'driver',
    ballSpeedMps: 60.7,
    clubSpeedMps: 42.1,
    smashFactor: 1.44,
    launchAngleDeg: 14.6,
    startDirectionDeg: 0.4,
    strike: { xMm: 1, yMm: 1 },
    confidence: 0.95,
    frameCount: 185,
    captureDurationMs: 599,
  }),
];

export const demoStatus: DeviceStatus = {
  name: 'LM1 · Demo',
  state: 'ready',
  firmwareVersion: '0.1.0-demo',
  cameraConnected: true,
  fps: 309,
  exposureUs: 125,
  temperatureC: 48,
  storageFreeGb: 22.6,
  calibrationVersion: 'CAL-014',
  lastSeenAt: new Date().toISOString(),
};

export function createDemoShot(number: number, clubId: ClubId): Shot {
  const phase = number % 5;
  const club = getClub(clubId);
  const clubSpeed = club.demoClubSpeedMps + (phase - 2) * 0.18;
  const smash = club.demoSmash + (phase - 2) * 0.006;
  const launchAngleDeg = club.demoLaunchDeg + (phase - 2) * 0.25;
  const ballSpeedMps = Number((clubSpeed * smash).toFixed(1));
  const startDirectionDeg = Number((-1.6 + phase * 0.8).toFixed(1));

  return withEstimatedCarry({
    id: `demo-${number}-${Date.now()}`,
    number,
    capturedAt: new Date().toISOString(),
    clubId,
    ballSpeedMps,
    clubSpeedMps: Number(clubSpeed.toFixed(1)),
    smashFactor: Number(smash.toFixed(2)),
    launchAngleDeg: Number(launchAngleDeg.toFixed(1)),
    startDirectionDeg,
    strike: { xMm: -4 + phase * 2.5, yMm: -2 + phase * 1.2 },
    confidence: 0.94 + phase * 0.006,
    frameCount: 184 + phase,
    captureDurationMs: 595 + phase * 3,
  });
}
