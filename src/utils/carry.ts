import { getClub, isClubId } from '@/data/clubs';
import { CaptureAnalysis, ClubId, ClubValueKey, DeviceShot, MetricConfidence, Shot, ShotMetricKey } from '@/types';
import { FlightEstimate, impactSpinRpm, LandingSurface, rollMeters, simulateFlight, spinLoftDeg } from '@/utils/flight';

export function assumedSpinRpm(clubId: ClubId, ballSpeedMps: number, attackAngleDeg?: number): number {
  const club = getClub(clubId);
  const referenceBallSpeed = club.demoClubSpeedMps * club.demoSmash;
  const speedRatio = Math.max(0.15, Math.min(1.25, ballSpeedMps / referenceBallSpeed));
  const attackFactor = attackAngleDeg != null && Number.isFinite(attackAngleDeg)
    ? Math.max(0.7, Math.min(1.3, 1 - 0.018 * attackAngleDeg)) : 1;
  return Math.round(club.typicalSpinRpm * speedRatio ** 0.7 * attackFactor);
}

export type SpinSource = 'camera' | 'impact-estimate' | 'club-attack-assumption';

/** Spin for the flight model, in order of evidence: camera, impact estimate, club average. Mirrors the Pi. */
export function selectSpin(clubId: ClubId, ballSpeedMps: number, launchAngleDeg: number, measuredRpm?: number | null,
  clubSpeedMps?: number | null, attackAngleDeg?: number | null): { rpm: number; source: SpinSource } {
  const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
  if (finite(measuredRpm)) return { rpm: measuredRpm, source: 'camera' };
  const impact = finite(clubSpeedMps) && finite(attackAngleDeg)
    ? impactSpinRpm(clubId, clubSpeedMps, launchAngleDeg, attackAngleDeg) : null;
  if (impact !== null) return { rpm: impact, source: 'impact-estimate' };
  return { rpm: assumedSpinRpm(clubId, ballSpeedMps, finite(attackAngleDeg) ? attackAngleDeg : undefined), source: 'club-attack-assumption' };
}

/**
 * Still-air flight model (fitted to tour averages): drag and backspin lift, landing
 * at launch height. This is always an estimate, never an observed landing distance.
 */
export function estimateCarryMeters({
  ballSpeedMps,
  launchAngleDeg,
  startDirectionDeg,
  clubId,
  spinRpm,
  attackAngleDeg,
}: Pick<Shot, 'ballSpeedMps' | 'launchAngleDeg' | 'startDirectionDeg' | 'clubId'> &
  { spinRpm?: number; attackAngleDeg?: number }): number {
  const spin = Number.isFinite(spinRpm) ? spinRpm! : assumedSpinRpm(clubId, ballSpeedMps, attackAngleDeg);
  const flight = simulateFlight(ballSpeedMps, launchAngleDeg, startDirectionDeg, spin);
  return flight ? Math.round(flight.carryM * 10) / 10 : 0;
}

export interface ShotEstimates {
  flight: FlightEstimate;
  rollM: number;
  /** Carry plus roll, along the target line. */
  totalM: number;
  surface: LandingSurface;
  spinRpm: number;
  spinLoftDeg: number | null;
  dynamicLoftDeg: number | null;
}

/** Model values derived from a shot's measured launch; every one is an estimate. */
export function shotEstimates(shot: Shot): ShotEstimates | null {
  const spin = Number.isFinite(shot.spinRpm) ? shot.spinRpm!
    : selectSpin(shot.clubId, shot.ballSpeedMps, shot.launchAngleDeg, null, shot.clubSpeedMps, shot.attackAngleDeg).rpm;
  const flight = simulateFlight(shot.ballSpeedMps, shot.launchAngleDeg, shot.startDirectionDeg, spin);
  if (!flight) return null;
  const { rollM, surface } = rollMeters(flight);
  const loft = shot.attackAngleDeg != null && Number.isFinite(shot.attackAngleDeg)
    ? spinLoftDeg(shot.launchAngleDeg, shot.attackAngleDeg) : null;
  const heading = Math.max(-90, Math.min(90, shot.startDirectionDeg)) * Math.PI / 180;
  return {
    flight, rollM, surface, spinRpm: spin,
    totalM: (flight.flightM + rollM) * Math.cos(heading),
    spinLoftDeg: loft,
    dynamicLoftDeg: loft === null ? null : loft + shot.attackAngleDeg!,
  };
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
    estimatedCarryM: shot.simulated ? (shot.estimatedCarryM ?? estimateCarryMeters(normalized)) : estimateCarryMeters(normalized),
  };
}

type CaptureMetric = NonNullable<CaptureAnalysis['measurements']>['metrics'][string];

const clubEstimate = (confidence: number, reason: string): MetricConfidence => ({ confidence, source: 'club-estimate', reason });

/** The Pi grades each value; older firmware without grades falls back to a flat estimate. */
function fromDevice(metric: CaptureMetric): MetricConfidence {
  const source = metric.status === 'measured' ? 'measured' : 'device-estimate';
  const confidence = metric.confidence ?? (source === 'measured' ? 0.9 : 0.7);
  return { confidence, source, reason: metric.reason, checks: metric.checks };
}

/**
 * Creates a shot only when the camera resolved the launch vector. A shot whose
 * club was not tracked is kept with club values null; only movement the Pi
 * classified as not a strike (nudge, re-placed ball, roll) is dropped.
 */
export function estimateShotFromCapture(capture: CaptureAnalysis, fallbackClub: ClubId, number: number): Shot | null {
  if (capture.mode !== 'full-shot' || capture.classification !== 'motion-observed') return null;
  if (capture.measurements?.shotEvidence?.status === 'not-a-strike') return null;
  const required = ['ballSpeedMps', 'launchAngleDeg', 'startDirectionDeg'] as const;
  if (required.some((key) => {
    const value = capture.measurements?.metrics[key]?.value;
    return typeof value !== 'number' || !Number.isFinite(value) || (key === 'ballSpeedMps' && value <= 0);
  })) return null;
  const clubId = isClubId(capture.clubId) ? capture.clubId : fallbackClub;
  const club = getClub(clubId);
  const metrics = capture.measurements?.metrics ?? {};
  const quality: Partial<Record<ShotMetricKey, MetricConfidence>> = {};
  const value = (key: string, fallback: number, confidence: number): number => {
    const metric = metrics[key];
    if (typeof metric?.value === 'number' && Number.isFinite(metric.value)) {
      quality[key as ShotMetricKey] = fromDevice(metric);
      return metric.value;
    }
    const why = metric?.reason ? ` The camera could not provide it: ${metric.reason}` : '';
    quality[key as ShotMetricKey] = clubEstimate(confidence, `Typical ${club.label} value from the club profile.${why}`);
    return fallback;
  };

  /** A camera value, or null with the device's reason recorded - never a club-profile number. */
  const unavailableReasons: NonNullable<Shot['unavailableReasons']> = {};
  const measured = (key: ClubValueKey, metricKey: string = key): number | null => {
    const metric = metrics[metricKey];
    if (typeof metric?.value === 'number' && Number.isFinite(metric.value)) {
      quality[key] = fromDevice(metric);
      return metric.value;
    }
    unavailableReasons[key] = metric?.reason ?? 'The camera did not report this value.';
    return null;
  };
  const launchAngleDeg = value('launchAngleDeg', club.demoLaunchDeg, 0.42);
  const ballSpeedMps = value('ballSpeedMps', 0, 0.25);
  const clubSpeedMps = measured('clubSpeedMps');
  let smashFactor = measured('smashFactor');
  if (smashFactor === null && clubSpeedMps !== null && clubSpeedMps > 0) {
    // Smash is the ratio of the two speeds, so it can be no better than the weaker of them.
    const inputs = [quality.ballSpeedMps, quality.clubSpeedMps];
    const checks = inputs.map((item, index) => ({
      label: `${index === 0 ? 'Ball' : 'Club'} speed measured`,
      passed: item?.source === 'measured',
    }));
    smashFactor = Number((ballSpeedMps / clubSpeedMps).toFixed(2));
    delete unavailableReasons.smashFactor;
    quality.smashFactor = {
      confidence: Math.min(...inputs.map((item) => item?.confidence ?? 0.2)),
      source: checks.every((check) => check.passed) ? 'measured' : 'device-estimate',
      reason: 'Ball speed divided by club speed.', checks,
    };
  }
  const startDirectionDeg = value('startDirectionDeg', 0, 0.2);
  const strikeX = measured('strike', 'strikeXmm');
  const strikeY = metrics.strikeYmm?.value;
  const strike = strikeX !== null && typeof strikeY === 'number' && Number.isFinite(strikeY)
    ? { xMm: strikeX, yMm: strikeY } : null;
  if (!strike) {
    delete quality.strike;
    unavailableReasons.strike ??= metrics.strikeYmm?.reason ?? 'The camera did not report face contact.';
  }
  const attackAngleDeg = measured('attackAngleDeg') ?? undefined;
  const clubPathDeg = measured('clubPathDeg') ?? undefined;
  const spin = selectSpin(clubId, ballSpeedMps, launchAngleDeg, metrics.spinRpm?.value, clubSpeedMps, attackAngleDeg);
  const spinRpm = spin.rpm;
  if (spin.source === 'camera') {
    quality.spinRpm = fromDevice(metrics.spinRpm!);
  } else if (spin.source === 'impact-estimate') {
    quality.spinRpm = {
      confidence: 0.4, source: 'model-estimate',
      reason: `Estimated ${spinRpm} rpm from the camera's club speed (${clubSpeedMps!.toFixed(1)} m/s), launch (${launchAngleDeg.toFixed(1)}°) and attack angle (${attackAngleDeg!.toFixed(1)}°): spin grows with club speed and how far launch sits above the attack angle. Fitted to tour averages; short-game use is extrapolated. Not camera-measured.`,
    };
  } else {
    quality.spinRpm = clubEstimate(attackAngleDeg == null ? 0.25 : 0.35,
      `Assumed ${spinRpm} rpm from the ${club.label} average and this shot's speed${attackAngleDeg == null ? '; attack angle unavailable' : `, adjusted for ${attackAngleDeg.toFixed(1)}° attack angle`}. Not camera-measured.`);
  }
  const spinAxisDeg = value('spinAxisDeg', 0, 0.15);

  const partial: Shot = {
    id: capture.id,
    number,
    capturedAt: capture.capturedAt,
    clubId,
    ballSpeedMps,
    clubSpeedMps,
    smashFactor,
    launchAngleDeg,
    startDirectionDeg,
    strike,
    spinRpm,
    spinAxisDeg,
    attackAngleDeg,
    clubPathDeg,
    confidence: Math.min(...Object.values(quality).map((item) => item?.confidence ?? 0.2)),
    metricConfidence: quality,
    unavailableReasons,
    frameCount: capture.frameCount,
    captureDurationMs: capture.captureDurationMs,
    captureId: capture.captureId ?? undefined,
    impactFrameIndex: capture.impactFrameIndex,
    coarseDepartureFrameIndex: capture.coarseDepartureFrameIndex,
    lastStationaryFrameIndex: capture.lastStationaryFrameIndex ?? undefined,
    firstMovingFrameIndex: capture.firstMovingFrameIndex ?? undefined,
    estimatedCarryM: 0,
    measurementSource: 'camera-estimate',
  };
  partial.estimatedCarryM = estimateCarryMeters({ ...partial, attackAngleDeg });
  quality.estimatedCarryM = {
    confidence: Math.min(quality.ballSpeedMps?.confidence ?? 0.5, quality.launchAngleDeg?.confidence ?? 0.5,
      quality.startDirectionDeg?.confidence ?? 0.5, spin.source === 'camera' ? 0.75 : spin.source === 'impact-estimate' ? 0.6 : 0.5),
    source: 'model-estimate',
    reason: `Still-air flight model fitted to tour averages (carry within about 7% for driver to wedge) from ball speed, launch angle, target-line direction and ${spin.source === 'camera' ? 'camera-measured' : spin.source === 'impact-estimate' ? 'impact-estimated' : 'assumed'} spin. Landing is not observed; wind, terrain and spin axis are not modeled.`,
  };
  return partial;
}

export const YARDS_PER_METER = 1.09361;

export function metersToYards(meters: number): number {
  return Math.round(meters * YARDS_PER_METER);
}
