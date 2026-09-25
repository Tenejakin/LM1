import { clubs } from '@/data/clubs';
import { ClubId, Shot } from '@/types';
import { shotEstimates } from '@/utils/carry';
import { measuredClubSpeed, measuredSmash } from '@/utils/shotValues';

export interface Spread {
  mean: number;
  /** Sample standard deviation; null with fewer than two values. */
  sd: number | null;
  min: number;
  max: number;
  count: number;
}

export interface ClubSummary {
  clubId: ClubId;
  shots: number;
  ballSpeedMps: Spread;
  launchAngleDeg: Spread;
  carryM: Spread;
  totalM: Spread;
  /** Negative is left, as with start direction. */
  offlineM: Spread;
  spinRpm: Spread | null;
  /** Only shots where the camera resolved the club contribute. */
  clubSpeedMps: Spread | null;
  smashFactor: Spread | null;
  attackAngleDeg: Spread | null;
  /** Average carry minus the next-shorter club's average carry; null for the shortest. */
  gapToNextM: number | null;
}

export function spread(values: number[]): Spread | null {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return null;
  const mean = finite.reduce((sum, value) => sum + value, 0) / finite.length;
  const sd = finite.length > 1
    ? Math.sqrt(finite.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (finite.length - 1)) : null;
  return { mean, sd, min: Math.min(...finite), max: Math.max(...finite), count: finite.length };
}

/** Shots that count toward session statistics. */
export function includedShots(shots: Shot[]): Shot[] {
  return shots.filter((shot) => !shot.excluded && !shot.simulated);
}

/** Per-club averages, dispersion and gapping, longest club first. */
export function clubSummaries(shots: Shot[]): ClubSummary[] {
  const byClub = new Map<ClubId, Shot[]>();
  for (const shot of includedShots(shots)) byClub.set(shot.clubId, [...(byClub.get(shot.clubId) ?? []), shot]);
  const summaries: ClubSummary[] = [];
  for (const [clubId, group] of byClub) {
    const estimates = group.map((shot) => ({ shot, estimate: shotEstimates(shot) }));
    const flown = estimates.filter((item) => item.estimate !== null);
    const numbers = (values: (number | null | undefined)[]) =>
      values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
    const carry = spread(flown.map((item) => item.estimate!.flight.carryM));
    if (!carry) continue;
    summaries.push({
      clubId,
      shots: group.length,
      ballSpeedMps: spread(group.map((shot) => shot.ballSpeedMps))!,
      launchAngleDeg: spread(group.map((shot) => shot.launchAngleDeg))!,
      carryM: carry,
      totalM: spread(flown.map((item) => item.estimate!.totalM))!,
      offlineM: spread(flown.map((item) => item.estimate!.flight.offlineM))!,
      spinRpm: spread(flown.map((item) => item.estimate!.spinRpm)),
      clubSpeedMps: spread(numbers(group.map(measuredClubSpeed))),
      smashFactor: spread(numbers(group.map(measuredSmash))),
      attackAngleDeg: spread(numbers(group.map((shot) => shot.attackAngleDeg))),
      gapToNextM: null,
    });
  }
  const order = (clubId: ClubId) => clubs.findIndex((club) => club.id === clubId);
  summaries.sort((a, b) => b.carryM.mean - a.carryM.mean || order(a.clubId) - order(b.clubId));
  summaries.forEach((summary, index) => {
    const next = summaries[index + 1];
    summary.gapToNextM = next ? summary.carryM.mean - next.carryM.mean : null;
  });
  return summaries;
}
