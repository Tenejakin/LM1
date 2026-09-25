from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch_measurements import grade_metrics, unavailable


def shot(**values):
    metrics = unavailable('fixture')
    for key, value in values.items():
        metrics[key]['value'] = value
    return {'metrics': metrics, 'clubTrack3d': [{} for _ in range(6)], 'spinSamples': [{}] * 5, 'diagnostics': {}}


CLEAN_FIT = {'frames': 14, 'rmsPx': 0.6, 'speedSigmaMps': 0.2, 'launchSigmaDeg': 0.8,
             'flightLaunchSigmaDeg': 0.8, 'headingSigmaDeg': 0.5}


class MetricGradingTest(unittest.TestCase):
    def context(self, **overrides):
        return {'poseErrorPx': 0.5, 'ballFit': dict(CLEAN_FIT), 'targetLineSource': 'rolled-ball', **overrides}

    def test_clean_fit_is_measured(self):
        result = shot(ballSpeedMps=40.0, launchAngleDeg=12.0, startDirectionDeg=1.0, clubSpeedMps=30.0, smashFactor=1.33)
        grade_metrics(result, self.context())
        for key in ('ballSpeedMps', 'launchAngleDeg', 'startDirectionDeg', 'clubSpeedMps', 'smashFactor'):
            self.assertEqual(result['metrics'][key]['status'], 'measured', key)
            self.assertTrue(all(check['passed'] for check in result['metrics'][key]['checks']))

    def test_confidence_falls_with_pose_error_and_explains_why(self):
        clean, noisy = shot(ballSpeedMps=40.0), shot(ballSpeedMps=40.0)
        grade_metrics(clean, self.context())
        grade_metrics(noisy, self.context(poseErrorPx=2.5))
        metric = noisy['metrics']['ballSpeedMps']
        self.assertEqual(metric['status'], 'estimated')
        self.assertLess(metric['confidence'], clean['metrics']['ballSpeedMps']['confidence'])
        failed = [check['label'] for check in metric['checks'] if not check['passed']]
        self.assertEqual(len(failed), 1)
        self.assertIn('2.50 px', failed[0])

    def test_estimates_are_no_longer_pinned_to_one_value(self):
        confidences = set()
        for pose in (1.2, 1.8, 2.8):
            result = shot(ballSpeedMps=40.0)
            grade_metrics(result, self.context(poseErrorPx=pose))
            confidences.add(result['metrics']['ballSpeedMps']['confidence'])
        self.assertEqual(len(confidences), 3)

    def test_models_and_assumptions_stay_estimates(self):
        result = shot(ballSpeedMps=40.0, launchAngleDeg=12.0, startDirectionDeg=1.0, estimatedCarryM=150.0,
                      strikeXmm=2.0, strikeYmm=1.0)
        grade_metrics(result, self.context(targetLineSource='camera-axis'))
        metrics = result['metrics']
        self.assertEqual(metrics['ballSpeedMps']['status'], 'measured')
        self.assertEqual(metrics['startDirectionDeg']['status'], 'measured')
        for key in ('estimatedCarryM', 'strikeXmm'):
            self.assertEqual(metrics[key]['status'], 'estimated', key)

    def test_silhouette_fallback_and_tagless_club_are_estimates(self):
        result = shot(ballSpeedMps=40.0, clubSpeedMps=30.0, smashFactor=1.33)
        result['diagnostics']['clubSilhouette'] = {'acceptedFrames': 9}
        grade_metrics(result, self.context(ballFit=None, guided=True))
        metrics = result['metrics']
        self.assertEqual(metrics['ballSpeedMps']['status'], 'estimated')
        self.assertEqual(metrics['clubSpeedMps']['status'], 'estimated')
        self.assertEqual(metrics['smashFactor']['status'], 'estimated')
        self.assertEqual(metrics['smashFactor']['confidence'],
                         min(metrics['ballSpeedMps']['confidence'], metrics['clubSpeedMps']['confidence']))

    def test_ball_size_disagreeing_with_calibration_blocks_measured(self):
        agree, disagree = shot(ballSpeedMps=40.0), shot(ballSpeedMps=40.0)
        grade_metrics(agree, self.context(ballFit={**CLEAN_FIT, 'ballSizeRatio': 0.97}))
        grade_metrics(disagree, self.context(ballFit={**CLEAN_FIT, 'ballSizeRatio': 0.83}))
        self.assertEqual(agree['metrics']['ballSpeedMps']['status'], 'measured')
        metric = disagree['metrics']['ballSpeedMps']
        self.assertEqual(metric['status'], 'estimated')
        self.assertIn('42.67 mm', next(check['label'] for check in metric['checks'] if not check['passed']))

    def test_unreported_values_are_left_alone(self):
        result = shot()
        grade_metrics(result, self.context())
        self.assertTrue(all(metric['status'] == 'unavailable' and 'checks' not in metric
                            for metric in result['metrics'].values()))


if __name__ == '__main__':
    unittest.main()
