/**
 * Still-air flight, roll and impact estimates - the same model as the Pi's
 * flight_model.py 2.0.0, so both compute the same carry. Nothing here is observed:
 * landing is never measured.
 *
 * Aerodynamics are fitted to the Trackman PGA Tour averages (driver to pitching
 * wedge): carry lands within 1-7% of those averages, with height and landing angle
 * close. Chips and skulls sit outside that envelope and are extrapolation.
 */
import { ClubId } from '@/types';

const GRAVITY = 9.80665;
const BALL_MASS_KG = 0.04593;
const BALL_RADIUS_M = 0.021335;
const AIR_DENSITY = 1.225;
const STEP_S = 0.002;
const MAX_FLIGHT_S = 15;
const DRAG_BASE = 0.237;
const DRAG_PER_SPIN_PARAMETER = 0.271;
const DRAG_PER_SPEED = 0.036;
const LIFT_SCALE = 0.495;
const LIFT_EXPONENT = 0.417;
const SPIN_DECAY_PER_S = 0.06;
/** spin = K x club speed x sin(launch - attack), K fitted per club to tour averages. */
const SPIN_LOFT_K: Record<ClubId, number> = {
  driver: 252, '3-wood': 365, '5-wood': 430, '3-hybrid': 419, '4-hybrid': 436,
  '4-iron': 453, '5-iron': 469, '6-iron': 485, '7-iron': 501, '8-iron': 535,
  '9-iron': 536, 'pitching-wedge': 514, 'gap-wedge': 514, 'sand-wedge': 514, 'lob-wedge': 514,
};
/** c = (2/7)(1 + m/M)/(1 + e) for a ball rolling off the face; see flight_model.py. */
const FACE_TANGENT_RATIO = 0.19;
const MAX_LAUNCH_ABOVE_ATTACK_DEG = 40;
const TURF_ABSORPTION = 0.162;
const GREEN_ROLL_FRICTION = 0.065;
const FAIRWAY_ROLL_FRICTION = 0.304;
const GREEN_MAX_CARRY_M = 40;
const GREEN_MIN_DESCENT_DEG = 20;

const toRad = (degrees: number) => degrees * Math.PI / 180;
const toDeg = (radians: number) => radians * 180 / Math.PI;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

export interface FlightEstimate {
  /** Along the target line. */
  carryM: number;
  /** Straight-line lateral distance at landing; curvature is not modeled. Negative is left. */
  offlineM: number;
  apexM: number;
  descentDeg: number;
  flightTimeS: number;
  landingHorizontalMps: number;
  landingVerticalMps: number;
  landingSpinRpm: number;
  /** Ground distance flown along the ball's own heading. */
  flightM: number;
}

export function simulateFlight(ballSpeedMps: number, launchAngleDeg: number, directionDeg: number, spinRpm: number): FlightEstimate | null {
  if (![ballSpeedMps, launchAngleDeg, directionDeg, spinRpm].every(finite) || ballSpeedMps <= 0) return null;
  const angle = toRad(Math.max(-10, Math.min(80, launchAngleDeg)));
  const direction = toRad(Math.max(-90, Math.min(90, directionDeg)));
  let vx = ballSpeedMps * Math.cos(angle);
  let vz = ballSpeedMps * Math.sin(angle);
  let x = 0;
  let z = 0;
  let t = 0;
  let apex = 0;
  const constant = 0.5 * AIR_DENSITY * Math.PI * BALL_RADIUS_M ** 2 / BALL_MASS_KG;
  const omega0 = Math.max(0, spinRpm) * 2 * Math.PI / 60;
  while (t < MAX_FLIGHT_S) {
    const speed = Math.hypot(vx, vz);
    if (speed < 0.01) break;
    const spinParameter = omega0 * Math.exp(-SPIN_DECAY_PER_S * t) * BALL_RADIUS_M / speed;
    const drag = Math.max(0.1, DRAG_BASE + DRAG_PER_SPIN_PARAMETER * spinParameter - DRAG_PER_SPEED * (speed / 50 - 1));
    const lift = LIFT_SCALE * spinParameter ** LIFT_EXPONENT;
    const ax = -constant * speed * (drag * vx + lift * vz);
    const az = -GRAVITY - constant * speed * (drag * vz - lift * vx);
    const nextX = x + vx * STEP_S + 0.5 * ax * STEP_S ** 2;
    const nextZ = z + vz * STEP_S + 0.5 * az * STEP_S ** 2;
    if (nextZ <= 0 && t > 0) {
      const fraction = z > nextZ ? z / (z - nextZ) : 1;
      x += (nextX - x) * fraction;
      vx += ax * STEP_S * fraction;
      vz += az * STEP_S * fraction;
      t += STEP_S * fraction;
      break;
    }
    x = nextX;
    z = nextZ;
    vx += ax * STEP_S;
    vz += az * STEP_S;
    t += STEP_S;
    apex = Math.max(apex, z);
  }
  return {
    carryM: Math.max(0, x * Math.cos(direction)), offlineM: x * Math.sin(direction), apexM: apex,
    descentDeg: toDeg(Math.atan2(-vz, vx)), flightTimeS: t, landingHorizontalMps: vx, landingVerticalMps: -vz,
    landingSpinRpm: Math.max(0, spinRpm) * Math.exp(-SPIN_DECAY_PER_S * t), flightM: x,
  };
}

export type LandingSurface = 'green' | 'fairway';

/** Slide to rolling with backspin, turf absorbs part of the normal speed, then roll-out. */
export function rollMeters(flight: FlightEstimate): { rollM: number; surface: LandingSurface } {
  const omega = flight.landingSpinRpm * 2 * Math.PI / 60;
  const rolling = Math.max(0, (5 * flight.landingHorizontalMps - 2 * BALL_RADIUS_M * omega) / 7
    - TURF_ABSORPTION * flight.landingVerticalMps);
  const surface: LandingSurface = flight.flightM < GREEN_MAX_CARRY_M && flight.descentDeg >= GREEN_MIN_DESCENT_DEG ? 'green' : 'fairway';
  return { rollM: rolling ** 2 / (2 * GRAVITY * (surface === 'green' ? GREEN_ROLL_FRICTION : FAIRWAY_ROLL_FRICTION)), surface };
}

/** Spin loft (dynamic loft minus attack angle) implied by launch and attack, or null. */
export function spinLoftDeg(launchAngleDeg: number, attackAngleDeg: number): number | null {
  const gap = launchAngleDeg - attackAngleDeg;
  if (!finite(gap) || gap <= 0 || gap > MAX_LAUNCH_ABOVE_ATTACK_DEG) return null;
  const target = toRad(gap);
  let low = 0;
  let high = toRad(80);
  for (let i = 0; i < 60; i++) {
    const middle = (low + high) / 2;
    if (middle - Math.atan(FACE_TANGENT_RATIO * Math.tan(middle)) < target) low = middle;
    else high = middle;
  }
  return toDeg(low);
}

/** Backspin from club speed and how far launch sits above the attack angle, or null. */
export function impactSpinRpm(clubId: ClubId, clubSpeedMps: number, launchAngleDeg: number, attackAngleDeg: number): number | null {
  if (![clubSpeedMps, launchAngleDeg, attackAngleDeg].every(finite) || clubSpeedMps <= 0) return null;
  const gap = launchAngleDeg - attackAngleDeg;
  if (gap <= 0 || gap > MAX_LAUNCH_ABOVE_ATTACK_DEG + 10) return null;
  return Math.round((SPIN_LOFT_K[clubId] ?? SPIN_LOFT_K['7-iron']) * clubSpeedMps * Math.sin(toRad(gap)));
}
