/** Left-to-right rig: the cameras sit on the right side of the target line. */
export function directionLabel(degrees: number): string {
  if (!Number.isFinite(degrees)) return 'Unavailable';
  if (Math.abs(degrees) < 0.05) return 'Straight';
  return `${Math.abs(degrees).toFixed(1)}° ${degrees > 0 ? 'R' : 'L'}`;
}

export const DIRECTION_SIGN_NOTE = 'R (+) is toward the cameras · L (−) is away from the cameras';
