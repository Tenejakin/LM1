export const KMH_PER_MPS = 3.6;
export const MPH_PER_MPS = 2.23694;

export function mpsToKmh(speedMps: number): number {
  return speedMps * KMH_PER_MPS;
}

export function kmhToMps(speedKmh: number): number {
  return speedKmh / KMH_PER_MPS;
}

export function mpsToMph(speedMps: number): number {
  return speedMps * MPH_PER_MPS;
}

export function mphToMps(speedMph: number): number {
  return speedMph / MPH_PER_MPS;
}
