import { PracticeSession, ReferenceShotData, Shot } from '@/types';
import { shotClubLabel } from '@/utils/bagClubs';
import { shotEstimates } from '@/utils/carry';
import { clubKey, spread, Spread } from '@/utils/session';
import { measuredAttackAngle, measuredClubPath, measuredClubSpeed, measuredSmash } from '@/utils/shotValues';

export const MAX_SESSION_NAME = 60;

export function newSessionId(): string {
  return `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** A name for a session started without one, from the local date and time. */
export function defaultSessionName(date = new Date()): string {
  return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} session`;
}

export function parseSessions(raw: string | null | undefined): PracticeSession[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((item): item is PracticeSession => Boolean(item) && typeof item.id === 'string'
        && typeof item.name === 'string' && typeof item.startedAt === 'string')
      : [];
  } catch {
    return [];
  }
}

/** Newest first, open sessions before closed ones. */
export function sortSessions(sessions: PracticeSession[]): PracticeSession[] {
  return [...sessions].sort((a, b) => Number(Boolean(a.endedAt)) - Number(Boolean(b.endedAt)) || b.startedAt.localeCompare(a.startedAt));
}

/** Shots of one session, or every shot with no session when sessionId is null. */
export function sessionShots(shots: Shot[], sessionId: string | null): Shot[] {
  return shots.filter((shot) => (sessionId === null ? !shot.sessionId : shot.sessionId === sessionId));
}

export type ComparisonKey = 'ballSpeedMps' | 'clubSpeedMps' | 'smashFactor' | 'launchAngleDeg' | 'startDirectionDeg'
  | 'spinRpm' | 'spinAxisDeg' | 'attackAngleDeg' | 'clubPathDeg' | 'carryM' | 'totalM' | 'apexM';

export type ComparisonUnit = 'speed' | 'ratio' | 'deg' | 'rpm' | 'distance';

export interface ComparisonMetric {
  key: ComparisonKey;
  label: string;
  unit: ComparisonUnit;
  /** LM1 side is a model estimate (carry, total, apex, usually spin), not a camera measurement. */
  lm1Estimated: boolean;
}

export const COMPARISON_METRICS: ComparisonMetric[] = [
  { key: 'ballSpeedMps', label: 'Ball speed', unit: 'speed', lm1Estimated: false },
  { key: 'clubSpeedMps', label: 'Club speed', unit: 'speed', lm1Estimated: false },
  { key: 'smashFactor', label: 'Smash', unit: 'ratio', lm1Estimated: false },
  { key: 'launchAngleDeg', label: 'Launch angle', unit: 'deg', lm1Estimated: false },
  { key: 'startDirectionDeg', label: 'Launch direction', unit: 'deg', lm1Estimated: false },
  { key: 'attackAngleDeg', label: 'Attack angle', unit: 'deg', lm1Estimated: false },
  { key: 'clubPathDeg', label: 'Club path', unit: 'deg', lm1Estimated: false },
  { key: 'spinRpm', label: 'Backspin', unit: 'rpm', lm1Estimated: true },
  { key: 'spinAxisDeg', label: 'Spin axis', unit: 'deg', lm1Estimated: true },
  { key: 'carryM', label: 'Carry', unit: 'distance', lm1Estimated: true },
  { key: 'totalM', label: 'Total', unit: 'distance', lm1Estimated: true },
  { key: 'apexM', label: 'Apex', unit: 'distance', lm1Estimated: true },
];

/** Signed angles: a mean near zero makes a percentage error meaningless. */
const SIGNED_KEYS: ComparisonKey[] = ['startDirectionDeg', 'spinAxisDeg', 'attackAngleDeg', 'clubPathDeg'];

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** LM1's value for a comparison metric: camera values only where the camera resolved them, model values otherwise. */
export function lm1Value(shot: Shot, key: ComparisonKey): number | null {
  switch (key) {
    case 'ballSpeedMps': return finite(shot.ballSpeedMps) ? shot.ballSpeedMps : null;
    case 'clubSpeedMps': return measuredClubSpeed(shot);
    case 'smashFactor': return measuredSmash(shot);
    case 'launchAngleDeg': return finite(shot.launchAngleDeg) ? shot.launchAngleDeg : null;
    case 'startDirectionDeg': return finite(shot.startDirectionDeg) ? shot.startDirectionDeg : null;
    case 'attackAngleDeg': return measuredAttackAngle(shot);
    case 'clubPathDeg': return measuredClubPath(shot);
    case 'spinRpm': return finite(shot.spinRpm) ? shot.spinRpm : null;
    case 'spinAxisDeg': {
      // The app stores 0 when the camera saw no spin axis; that is a placeholder, not a reading.
      // The Pi reports positive as a draw (curves left); reference monitors use positive for a fade.
      const source = shot.metricConfidence?.spinAxisDeg?.source;
      return finite(shot.spinAxisDeg) && (source === 'measured' || source === 'device-estimate') ? -shot.spinAxisDeg : null;
    }
    case 'carryM': return finite(shot.estimatedCarryM) && shot.estimatedCarryM > 0 ? shot.estimatedCarryM : null;
    case 'totalM': { const estimate = shotEstimates(shot); return estimate ? estimate.totalM : null; }
    case 'apexM': { const estimate = shotEstimates(shot); return estimate ? estimate.flight.apexM : null; }
    default: return null;
  }
}

/** Whether LM1's spin on this shot came from a model rather than the camera. */
export function lm1SpinEstimated(shot: Shot): boolean {
  return shot.metricConfidence?.spinRpm?.source !== 'measured';
}

/** The reference value, with smash derived from the two speeds when it was not typed. */
export function referenceValue(reference: ReferenceShotData | undefined, key: ComparisonKey): number | null {
  if (!reference) return null;
  if (key === 'smashFactor') {
    return finite(reference.ballSpeedMps) && finite(reference.clubSpeedMps) && reference.clubSpeedMps > 0
      ? reference.ballSpeedMps / reference.clubSpeedMps : null;
  }
  const value = reference[key];
  return finite(value) ? value : null;
}

export interface MetricComparison {
  metric: ComparisonMetric;
  /** Shots with both an LM1 and a reference value. */
  pairs: { shotId: string; number: number; lm1: number; reference: number; delta: number }[];
  lm1: Spread;
  reference: Spread;
  /** LM1 minus reference; the mean is the bias. */
  delta: Spread;
  meanAbsDelta: number;
  /** Mean absolute error as a share of the reference mean; null for signed angles. */
  meanAbsPct: number | null;
}

export interface ReferenceComparison {
  /** Shots in the group that carry any reference numbers. */
  referencedShots: number;
  metrics: MetricComparison[];
}

/** Shot-by-shot agreement between LM1 and the typed-in reference monitor; excluded shots are left out. */
export function referenceComparison(shots: Shot[]): ReferenceComparison {
  const referenced = shots.filter((shot) => shot.reference && !shot.excluded);
  const metrics: MetricComparison[] = [];
  for (const metric of COMPARISON_METRICS) {
    const pairs = referenced.flatMap((shot) => {
      const lm1 = lm1Value(shot, metric.key);
      const reference = referenceValue(shot.reference, metric.key);
      return lm1 === null || reference === null ? [] : [{ shotId: shot.id, number: shot.number, lm1, reference, delta: lm1 - reference }];
    });
    if (!pairs.length) continue;
    const delta = spread(pairs.map((pair) => pair.delta))!;
    const reference = spread(pairs.map((pair) => pair.reference))!;
    const meanAbsDelta = pairs.reduce((sum, pair) => sum + Math.abs(pair.delta), 0) / pairs.length;
    metrics.push({
      metric, pairs, lm1: spread(pairs.map((pair) => pair.lm1))!, reference, delta, meanAbsDelta,
      meanAbsPct: !SIGNED_KEYS.includes(metric.key) && Math.abs(reference.mean) > 1e-6
        ? (meanAbsDelta / Math.abs(reference.mean)) * 100 : null,
    });
  }
  return { referencedShots: referenced.length, metrics };
}

export interface ClubComparison {
  key: string;
  label: string;
  shots: number;
  comparison: ReferenceComparison;
}

/** The same comparison split by named club, so a club with a bias stands out. */
export function clubComparisons(shots: Shot[]): ClubComparison[] {
  const groups = new Map<string, Shot[]>();
  for (const shot of shots) {
    if (!shot.reference || shot.excluded) continue;
    groups.set(clubKey(shot), [...(groups.get(clubKey(shot)) ?? []), shot]);
  }
  return [...groups.entries()].map(([key, group]) => {
    const newest = group.reduce((latest, shot) => (shot.capturedAt > latest.capturedAt ? shot : latest));
    return { key, label: shotClubLabel(newest), shots: group.length, comparison: referenceComparison(group) };
  }).sort((a, b) => b.shots - a.shots);
}

export interface CsvUnits {
  speedLabel: string;
  distanceLabel: string;
  speed: (mps: number) => number;
  distance: (meters: number) => number;
}

const csvCell = (value: string | number | null | undefined, digits = 2): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toFixed(digits) : '';
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
};

/** One row per shot with LM1 and reference values side by side, in the given display units. */
export function sessionCsv(session: PracticeSession | null, shots: Shot[], units: CsvUnits): string {
  const speed = (value: number | null) => (value === null ? null : units.speed(value));
  const distance = (value: number | null) => (value === null ? null : units.distance(value));
  const header = [
    'shot', 'captured_at', 'session', 'club', 'club_type', 'excluded', 'reference_device',
    `lm1_ball_${units.speedLabel}`, `ref_ball_${units.speedLabel}`,
    `lm1_club_${units.speedLabel}`, `ref_club_${units.speedLabel}`,
    'lm1_smash', 'ref_smash', 'lm1_launch_deg', 'ref_launch_deg', 'lm1_direction_deg', 'ref_direction_deg',
    'lm1_attack_deg', 'ref_attack_deg', 'lm1_path_deg', 'ref_path_deg',
    'lm1_spin_rpm', 'lm1_spin_source', 'ref_spin_rpm', 'lm1_spin_axis_deg', 'ref_spin_axis_deg',
    `lm1_carry_${units.distanceLabel}`, `ref_carry_${units.distanceLabel}`,
    `lm1_total_${units.distanceLabel}`, `ref_total_${units.distanceLabel}`,
    `lm1_apex_${units.distanceLabel}`, `ref_apex_${units.distanceLabel}`,
    'lm1_capture_id', 'notes',
  ];
  const identity = (value: number | null) => value;
  const rows = [...shots].sort((a, b) => a.capturedAt.localeCompare(b.capturedAt)).map((shot) => {
    const reference = shot.reference;
    const pair = (key: ComparisonKey, convert: (value: number | null) => number | null, digits: number) =>
      [csvCell(convert(lm1Value(shot, key)), digits), csvCell(convert(referenceValue(reference, key)), digits)];
    return [
      csvCell(shot.number, 0), csvCell(shot.capturedAt), csvCell(session?.name ?? ''), csvCell(shotClubLabel(shot)), csvCell(shot.clubId),
      csvCell(shot.excluded ? 'yes' : 'no'), csvCell(reference?.device ?? ''),
      ...pair('ballSpeedMps', speed, 1), ...pair('clubSpeedMps', speed, 1), ...pair('smashFactor', identity, 3),
      ...pair('launchAngleDeg', identity, 1), ...pair('startDirectionDeg', identity, 1),
      ...pair('attackAngleDeg', identity, 1), ...pair('clubPathDeg', identity, 1),
      csvCell(lm1Value(shot, 'spinRpm'), 0), csvCell(lm1SpinEstimated(shot) ? 'model' : 'camera'), csvCell(referenceValue(reference, 'spinRpm'), 0),
      ...pair('spinAxisDeg', identity, 1),
      ...pair('carryM', distance, 1), ...pair('totalM', distance, 1), ...pair('apexM', distance, 1),
      csvCell(shot.captureId ?? ''), csvCell(reference?.notes ?? ''),
    ].join(',');
  });
  return [header.join(','), ...rows].join('\n');
}
