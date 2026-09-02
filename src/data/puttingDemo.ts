import { Putt } from '@/types';

const now = Date.now();

export const demoPutts: Putt[] = [
  {
    id: 'demo-putt-18',
    number: 18,
    capturedAt: new Date(now - 90_000).toISOString(),
    ballSpeedMps: 1.82,
    putterSpeedMps: 1.28,
    smashFactor: 1.42,
    launchDirectionDeg: 0.35,
    launchAngleDeg: 1.6,
    strike: { xMm: 1.5, yMm: 0.5 },
    confidence: 0.97,
    frameCount: 162,
    captureDurationMs: 1_850,
    rollDistanceM: 3.05,
    skidDistanceM: 0.22,
  },
  {
    id: 'demo-putt-17',
    number: 17,
    capturedAt: new Date(now - 4 * 60_000).toISOString(),
    ballSpeedMps: 1.74,
    putterSpeedMps: 1.25,
    smashFactor: 1.39,
    launchDirectionDeg: -0.7,
    launchAngleDeg: 1.4,
    strike: { xMm: -2, yMm: 0 },
    confidence: 0.95,
    frameCount: 159,
    captureDurationMs: 1_790,
    rollDistanceM: 2.78,
    skidDistanceM: 0.2,
  },
  {
    id: 'demo-putt-16',
    number: 16,
    capturedAt: new Date(now - 7 * 60_000).toISOString(),
    ballSpeedMps: 1.9,
    putterSpeedMps: 1.31,
    smashFactor: 1.45,
    launchDirectionDeg: 1.1,
    launchAngleDeg: 1.8,
    strike: { xMm: 3, yMm: 1 },
    confidence: 0.96,
    frameCount: 164,
    captureDurationMs: 1_920,
    rollDistanceM: 3.28,
    skidDistanceM: 0.25,
  },
];

export function createDemoPutt(number: number): Putt {
  const phase = number % 5;
  const putterSpeedMps = 1.23 + phase * 0.025;
  const smashFactor = 1.39 + phase * 0.012;
  const ballSpeedMps = putterSpeedMps * smashFactor;
  const direction = -0.8 + phase * 0.38;

  return {
    id: `demo-putt-${number}-${Date.now()}`,
    number,
    capturedAt: new Date().toISOString(),
    ballSpeedMps: Number(ballSpeedMps.toFixed(2)),
    putterSpeedMps: Number(putterSpeedMps.toFixed(2)),
    smashFactor: Number(smashFactor.toFixed(2)),
    launchDirectionDeg: Number(direction.toFixed(2)),
    launchAngleDeg: Number((1.35 + phase * 0.1).toFixed(1)),
    strike: { xMm: -2 + phase, yMm: -0.5 + phase * 0.25 },
    confidence: 0.95 + phase * 0.006,
    frameCount: 158 + phase,
    captureDurationMs: 1_780 + phase * 30,
    rollDistanceM: Number((2.72 + phase * 0.13).toFixed(2)),
    skidDistanceM: Number((0.18 + phase * 0.015).toFixed(2)),
  };
}
