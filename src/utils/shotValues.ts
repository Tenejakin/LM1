import { ClubValueKey, Shot, StrikePoint } from '@/types';

/*
 * Club speed, smash and strike are only shown when the camera resolved them.
 * New camera shots carry null for a missing value; shots saved by older app
 * versions carry a club-profile number marked 'club-estimate', which is treated
 * the same way so a club constant is never displayed or averaged as a result.
 */

const estimated = (shot: Shot, key: ClubValueKey) => shot.metricConfidence?.[key]?.source === 'club-estimate';

export function measuredClubSpeed(shot: Shot): number | null {
  return shot.clubSpeedMps != null && Number.isFinite(shot.clubSpeedMps) && !estimated(shot, 'clubSpeedMps')
    ? shot.clubSpeedMps : null;
}

export function measuredSmash(shot: Shot): number | null {
  return shot.smashFactor != null && Number.isFinite(shot.smashFactor) && !estimated(shot, 'smashFactor')
    ? shot.smashFactor : null;
}

export function measuredAttackAngle(shot: Shot): number | null {
  return shot.attackAngleDeg != null && Number.isFinite(shot.attackAngleDeg) ? shot.attackAngleDeg : null;
}

export function measuredClubPath(shot: Shot): number | null {
  return shot.clubPathDeg != null && Number.isFinite(shot.clubPathDeg) ? shot.clubPathDeg : null;
}

export function measuredStrike(shot: Shot): StrikePoint | null {
  return shot.strike && !estimated(shot, 'strike') ? shot.strike : null;
}

/** Why a club value is missing, from the device's own reason when it gave one. */
export function unavailableReason(shot: Shot, key: ClubValueKey): string {
  return shot.unavailableReasons?.[key] ?? shot.metricConfidence?.[key]?.reason
    ?? 'The camera did not resolve this value for this shot.';
}
