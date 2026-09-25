import type { StereoCalibrationResult } from '@/types';

type ErrorMetric = { value: number; target: number; limit: number; weight: number };

function metricScore({ value, target, limit }: ErrorMetric): number {
  if (!Number.isFinite(value) || value < 0) return 0;
  if (value <= target) return 100;
  if (value <= limit) return 100 - 30 * (value - target) / (limit - target);
  return Math.max(0, 70 * (2 * limit - value) / limit);
}

/** Fit-margin guide. A 100 means all three errors meet the stated targets. */
export function stereoCalibrationScore(result: StereoCalibrationResult): number {
  const metrics: ErrorMetric[] = [
    { value: result.rmsPx, target: 0.35, limit: 0.7, weight: 0.3 },
    { value: result.validationRmsPx, target: 0.5, limit: 1, weight: 0.5 },
    { value: result.validationMaxPx, target: 1, limit: 2, weight: 0.2 },
  ];
  const score = Math.round(metrics.reduce((sum, metric) => sum + metric.weight * metricScore(metric), 0));
  return result.passed ? score : Math.min(score, 59);
}
