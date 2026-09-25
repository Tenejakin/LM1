import type { CaptureAnalysis, Putt } from '@/types';

/** Preserve measured putting inputs without inventing unavailable face contact. */
export function puttFromCapture(capture: CaptureAnalysis, number: number): Putt | null {
  if (capture.mode !== 'putting' || capture.classification !== 'motion-observed') return null;
  const metrics = capture.measurements?.metrics;
  const value = (key: string): number | null => {
    const candidate = metrics?.[key]?.value;
    return typeof candidate === 'number' && Number.isFinite(candidate) ? candidate : null;
  };
  const ballSpeedMps = value('ballSpeedMps');
  const putterSpeedMps = value('clubSpeedMps');
  const smashFactor = value('smashFactor');
  const launchAngleDeg = value('launchAngleDeg');
  const launchDirectionDeg = value('startDirectionDeg');
  if (ballSpeedMps === null || putterSpeedMps === null || smashFactor === null
    || launchAngleDeg === null || launchDirectionDeg === null
    || ballSpeedMps <= 0 || putterSpeedMps <= 0 || smashFactor <= 0 || smashFactor > 2.2) return null;
  const strikeX = value('strikeXmm');
  const strikeY = value('strikeYmm');
  const rollDistanceM = value('rollDistanceM');
  const skidDistanceM = value('skidDistanceM');
  return {
    id: capture.id,
    number,
    capturedAt: capture.capturedAt,
    captureId: capture.captureId ?? undefined,
    ballSpeedMps,
    putterSpeedMps,
    smashFactor,
    launchAngleDeg,
    launchDirectionDeg,
    strike: strikeX === null || strikeY === null ? null : { xMm: strikeX, yMm: strikeY },
    airborne: launchAngleDeg > 10,
    confidence: 0,
    frameCount: capture.frameCount,
    captureDurationMs: capture.captureDurationMs,
    impactFrameIndex: capture.impactFrameIndex,
    coarseDepartureFrameIndex: capture.coarseDepartureFrameIndex,
    lastStationaryFrameIndex: capture.lastStationaryFrameIndex ?? undefined,
    firstMovingFrameIndex: capture.firstMovingFrameIndex ?? undefined,
    rollDistanceM: rollDistanceM ?? undefined,
    skidDistanceM: skidDistanceM ?? undefined,
    measurementSource: 'monocular-estimate',
  };
}
