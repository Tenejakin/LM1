import { Putt } from '@/types';
import { directionLabel } from '@/utils/direction';

const STIMP_REFERENCE_SPEED_MPS = 1.83;

export function estimatePuttRollMeters(ballSpeedMps: number, stimpFeet: number): number {
  const safeSpeed = Math.max(0, Math.min(5, ballSpeedMps));
  const safeStimp = Math.max(5, Math.min(15, stimpFeet));
  const referenceRollM = safeStimp * 0.3048;
  return Number((referenceRollM * (safeSpeed / STIMP_REFERENCE_SPEED_MPS) ** 2).toFixed(2));
}

export function puttRollMeters(putt: Putt, stimpFeet: number): number {
  return putt.rollDistanceM ?? estimatePuttRollMeters(putt.ballSpeedMps, stimpFeet);
}

export function lateralMissCentimeters(directionDeg: number, targetDistanceM: number): number {
  const radians = Math.max(-15, Math.min(15, directionDeg)) * (Math.PI / 180);
  return Number((Math.tan(radians) * Math.max(0, targetDistanceM) * 100).toFixed(1));
}

export function paceLabel(rollDistanceM: number, targetDistanceM: number): string {
  const difference = rollDistanceM - targetDistanceM;
  if (Math.abs(difference) <= 0.15) return 'Perfect pace';
  return `${Math.abs(difference).toFixed(2)} m ${difference > 0 ? 'long' : 'short'}`;
}

export function startLineLabel(directionDeg: number): string {
  return directionLabel(directionDeg);
}
