import { getClub } from '@/data/clubs';
import { ClubId, DeviceShot, Shot } from '@/types';

const GRAVITY_MPS2 = 9.80665;

/**
 * Rough carry model for V1. It uses the measured launch vector and a
 * club-specific flight factor. Spin, wind, altitude and temperature are not
 * available yet, so this must always be presented as an estimate.
 */
export function estimateCarryMeters({
  ballSpeedMps,
  launchAngleDeg,
  startDirectionDeg,
  clubId,
}: Pick<Shot, 'ballSpeedMps' | 'launchAngleDeg' | 'startDirectionDeg' | 'clubId'>): number {
  const launch = Math.max(3, Math.min(45, launchAngleDeg)) * (Math.PI / 180);
  const offline = Math.min(30, Math.abs(startDirectionDeg)) * (Math.PI / 180);
  const baseRange = (ballSpeedMps ** 2 * Math.sin(2 * launch)) / GRAVITY_MPS2;
  const downRangeEfficiency = Math.cos(offline);
  const carry = baseRange * getClub(clubId).carryFactor * downRangeEfficiency;
  return Math.round(Math.max(0, Math.min(320, carry)));
}

export function normalizeShot(shot: DeviceShot, fallbackClub: ClubId): Shot {
  const clubId = shot.clubId ?? fallbackClub;
  const normalized: Shot = {
    ...shot,
    clubId,
    estimatedCarryM: 0,
  };

  return {
    ...normalized,
    estimatedCarryM: shot.estimatedCarryM ?? estimateCarryMeters(normalized),
  };
}

export function metersToYards(meters: number): number {
  return Math.round(meters * 1.09361);
}
