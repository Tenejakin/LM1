import { ReferenceShotData } from '@/types';

export const MPH_PER_MPS = 2.2369362920544;
export const YARDS_PER_METER = 1.0936132983377;
export const MAX_REFERENCE_DEVICE = 30;
export const MAX_REFERENCE_NOTES = 200;

export type Side = 'L' | 'R';

/** What the player types: numbers in the app's display units, sides as L/R so signs never need thought. */
export interface ReferenceDraft {
  device: string;
  ballSpeed: string;
  clubSpeed: string;
  launchAngle: string;
  launchDirection: string;
  launchDirectionSide: Side;
  spinRpm: string;
  spinAxis: string;
  /** Which way the ball curves: R is a fade for a right-hander. */
  spinAxisSide: Side;
  attackAngle: string;
  clubPath: string;
  /** Path direction: R is in-to-out for a right-hander. */
  clubPathSide: Side;
  carry: string;
  total: string;
  apex: string;
  notes: string;
}

export interface DraftUnits {
  speedUnit: 'mph' | 'kmh';
  distanceUnit: 'yd' | 'm';
}

export const toMps = (value: number, unit: DraftUnits['speedUnit']): number => (unit === 'mph' ? value / MPH_PER_MPS : value / 3.6);
export const toMeters = (value: number, unit: DraftUnits['distanceUnit']): number => (unit === 'yd' ? value / YARDS_PER_METER : value);
const fromMps = (mps: number, unit: DraftUnits['speedUnit']): number => (unit === 'mph' ? mps * MPH_PER_MPS : mps * 3.6);
const fromMeters = (meters: number, unit: DraftUnits['distanceUnit']): number => (unit === 'yd' ? meters * YARDS_PER_METER : meters);

const text = (value: number | null | undefined, digits: number): string =>
  value == null || !Number.isFinite(value) ? '' : String(Number(value.toFixed(digits)));

/** Absolute value as text plus the side of a signed angle; positive is R in the app. */
const signedText = (value: number | null | undefined, digits = 1): { text: string; side: Side } =>
  ({ text: text(value == null ? value : Math.abs(value), digits), side: (value ?? 0) < 0 ? 'L' : 'R' });

export function draftFromReference(reference: ReferenceShotData | null | undefined, units: DraftUnits, defaultDevice = 'GC3'): ReferenceDraft {
  const direction = signedText(reference?.startDirectionDeg);
  const axis = signedText(reference?.spinAxisDeg);
  const path = signedText(reference?.clubPathDeg);
  const speed = (mps: number | null | undefined) => text(mps == null ? mps : fromMps(mps, units.speedUnit), 1);
  const distance = (meters: number | null | undefined) => text(meters == null ? meters : fromMeters(meters, units.distanceUnit), 1);
  return {
    device: reference?.device ?? defaultDevice,
    ballSpeed: speed(reference?.ballSpeedMps), clubSpeed: speed(reference?.clubSpeedMps),
    launchAngle: text(reference?.launchAngleDeg, 1),
    launchDirection: direction.text, launchDirectionSide: direction.side,
    spinRpm: text(reference?.spinRpm, 0), spinAxis: axis.text, spinAxisSide: axis.side,
    attackAngle: text(reference?.attackAngleDeg, 1), clubPath: path.text, clubPathSide: path.side,
    carry: distance(reference?.carryM), total: distance(reference?.totalM), apex: distance(reference?.apexM),
    notes: reference?.notes ?? '',
  };
}

/** A number, null for an empty field, or undefined for text that is not a number. */
const optionalNumber = (value: string): number | null | undefined => {
  const trimmed = value.trim().replace(',', '.');
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
};

/** Reference data in SI and app signs, or the reason the draft cannot be saved. */
export function referenceFromDraft(draft: ReferenceDraft, units: DraftUnits, existing?: ReferenceShotData | null): ReferenceShotData | string {
  const device = draft.device.trim();
  if (!device) return 'Name the launch monitor the numbers came from, e.g. GC3.';
  if (device.length > MAX_REFERENCE_DEVICE) return `Keep the device name to ${MAX_REFERENCE_DEVICE} characters.`;
  const fields: { label: string; value: number | null | undefined; min: number; max: number }[] = [
    { label: 'Ball speed', value: optionalNumber(draft.ballSpeed), min: 0.5, max: units.speedUnit === 'mph' ? 250 : 400 },
    { label: 'Club speed', value: optionalNumber(draft.clubSpeed), min: 0.5, max: units.speedUnit === 'mph' ? 160 : 260 },
    { label: 'Launch angle', value: optionalNumber(draft.launchAngle), min: -10, max: 80 },
    { label: 'Launch direction', value: optionalNumber(draft.launchDirection), min: 0, max: 90 },
    { label: 'Backspin', value: optionalNumber(draft.spinRpm), min: 0, max: 20000 },
    { label: 'Spin axis', value: optionalNumber(draft.spinAxis), min: 0, max: 90 },
    { label: 'Attack angle', value: optionalNumber(draft.attackAngle), min: -30, max: 30 },
    { label: 'Club path', value: optionalNumber(draft.clubPath), min: 0, max: 45 },
    { label: 'Carry', value: optionalNumber(draft.carry), min: 0, max: units.distanceUnit === 'yd' ? 450 : 420 },
    { label: 'Total', value: optionalNumber(draft.total), min: 0, max: units.distanceUnit === 'yd' ? 500 : 460 },
    { label: 'Apex', value: optionalNumber(draft.apex), min: 0, max: units.distanceUnit === 'yd' ? 80 : 75 },
  ];
  for (const field of fields) {
    if (field.value === undefined) return `${field.label} must be a number.`;
    if (field.value !== null && (field.value < field.min || field.value > field.max)) {
      return `${field.label} must be between ${field.min} and ${field.max}.`;
    }
  }
  const at = (index: number): number | null => fields[index]?.value ?? null;
  const ball = at(0); const club = at(1); const launch = at(2); const direction = at(3); const spin = at(4);
  const axis = at(5); const attack = at(6); const path = at(7); const carry = at(8); const total = at(9); const apex = at(10);
  if (fields.every((field) => field.value === null)) return 'Enter at least one value from the other launch monitor.';
  if (ball !== null && club !== null && (ball / club < 0.5 || ball / club > 2)) {
    return 'Ball speed divided by club speed is outside 0.5 to 2.0; check the two speeds.';
  }
  if (carry !== null && total !== null && total < carry) return 'Total cannot be shorter than carry.';
  const sign = (side: Side) => (side === 'L' ? -1 : 1);
  return {
    device,
    enteredAt: existing?.enteredAt ?? new Date().toISOString(),
    ballSpeedMps: ball === null ? null : toMps(ball, units.speedUnit),
    clubSpeedMps: club === null ? null : toMps(club, units.speedUnit),
    launchAngleDeg: launch,
    startDirectionDeg: direction === null ? null : direction * sign(draft.launchDirectionSide),
    spinRpm: spin,
    spinAxisDeg: axis === null ? null : axis * sign(draft.spinAxisSide),
    attackAngleDeg: attack,
    clubPathDeg: path === null ? null : path * sign(draft.clubPathSide),
    carryM: carry === null ? null : toMeters(carry, units.distanceUnit),
    totalM: total === null ? null : toMeters(total, units.distanceUnit),
    apexM: apex === null ? null : toMeters(apex, units.distanceUnit),
    notes: draft.notes.trim().slice(0, MAX_REFERENCE_NOTES) || undefined,
  };
}
