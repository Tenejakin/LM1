import { getClub, isClubId } from '@/data/clubs';
import { CaptureAnalysis, ClubId, DeviceShot, MetricConfidence, Shot, ShotMetricKey } from '@/types';

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

const measured = (confidence = 0.9): MetricConfidence => ({ confidence, source: 'measured' });
const deviceEstimate = (confidence = 0.7): MetricConfidence => ({ confidence, source: 'device-estimate' });
const clubEstimate = (confidence: number): MetricConfidence => ({ confidence, source: 'club-estimate' });

/** Turns a motion-tracked camera result into a complete, clearly-labelled shot. */
export function estimateShotFromCapture(capture: CaptureAnalysis, fallbackClub: ClubId, number: number): Shot | null {
  if (capture.mode !== 'full-shot' || capture.classification !== 'motion-observed') return null;
  const clubId = isClubId(capture.clubId) ? capture.clubId : fallbackClub;
  const club = getClub(clubId);
  const metrics = capture.measurements?.metrics ?? {};
  const quality: Partial<Record<ShotMetricKey, MetricConfidence>> = {};
  const value = (key: string, fallback: number, confidence: number): number => {
    const metric = metrics[key];
    if (typeof metric?.value === 'number' && Number.isFinite(metric.value)) {
      quality[key as ShotMetricKey] = metric.status === 'measured' ? measured() : deviceEstimate();
      return metric.value;
    }
    quality[key as ShotMetricKey] = clubEstimate(confidence);
    return fallback;
  };

  const launchAngleDeg = value('launchAngleDeg', club.demoLaunchDeg, 0.42);
  const ballSpeedFallback = club.demoClubSpeedMps * club.demoSmash;
  const ballSpeedMps = value('ballSpeedMps', ballSpeedFallback, 0.25);
  const clubSpeedMps = value('clubSpeedMps', ballSpeedMps / club.demoSmash, 0.48);
  const measuredSmash = metrics.smashFactor?.value;
  const smashFactor = typeof measuredSmash === 'number' && Number.isFinite(measuredSmash)
    ? value('smashFactor', club.demoSmash, 0.45)
    : Number((ballSpeedMps / Math.max(0.1, clubSpeedMps)).toFixed(2));
  if (!(typeof measuredSmash === 'number' && Number.isFinite(measuredSmash))) {
    // Smash is the ratio of the two speeds, so it can be no better than the weaker
    // of them. When club speed is itself the profile fallback (ballSpeed / demoSmash)
    // the ratio collapses to demoSmash exactly - a club constant that cannot vary
    // with the strike - so it must never inherit the ball measurement's confidence.
    const inputs = [quality.ballSpeedMps, quality.clubSpeedMps];
    const confidence = Math.min(...inputs.map((item) => item?.confidence ?? 0.2));
    quality.smashFactor = inputs.some((item) => item?.source === 'club-estimate')
      ? clubEstimate(confidence)
      : deviceEstimate(confidence);
  }
  const startDirectionDeg = value('startDirectionDeg', 0, 0.2);
  const strikeXMetric = metrics.strikeXmm;
  const strikeYMetric = metrics.strikeYmm;
  const strikeX = typeof strikeXMetric?.value === 'number' ? strikeXMetric.value : 0;
  const strikeY = typeof strikeYMetric?.value === 'number' ? strikeYMetric.value : 0;
  quality.strike = strikeXMetric?.value != null && strikeYMetric?.value != null
    ? deviceEstimate(0.65)
    : clubEstimate(0.18);
  const launchDifference = launchAngleDeg - club.demoLaunchDeg;
  const estimatedSpin = Math.round(club.typicalSpinRpm * Math.max(0.72, Math.min(1.28, 1 + launchDifference * 0.018)));
  const spinRpm = value('spinRpm', estimatedSpin, 0.35);
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
    strike: { xMm: strikeX, yMm: strikeY },
    spinRpm,
    spinAxisDeg,
    confidence: Math.min(...Object.values(quality).map((item) => item?.confidence ?? 0.2)),
    metricConfidence: quality,
    frameCount: capture.frameCount,
    captureDurationMs: capture.captureDurationMs,
    captureId: capture.captureId ?? undefined,
    impactFrameIndex: capture.impactFrameIndex,
    coarseDepartureFrameIndex: capture.coarseDepartureFrameIndex,
    lastStationaryFrameIndex: capture.lastStationaryFrameIndex ?? undefined,
    firstMovingFrameIndex: capture.firstMovingFrameIndex ?? undefined,
    estimatedCarryM: 0,
    measurementSource: 'monocular-estimate',
  };
  partial.estimatedCarryM = metrics.estimatedCarryM?.value ?? estimateCarryMeters(partial);
  quality.estimatedCarryM = metrics.estimatedCarryM?.value != null ? deviceEstimate(0.55) : clubEstimate(0.4);
  return partial;
}

export const YARDS_PER_METER = 1.09361;

export function metersToYards(meters: number): number {
  return Math.round(meters * YARDS_PER_METER);
}
