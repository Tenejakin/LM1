"""Review unit and sign checks 0.1.0."""
import unittest
from full_shot_review import pair_metrics

class ReviewMathTests(unittest.TestCase):
    def test_nanoseconds_and_metric_scale(self):
        a={'timestamp':1000000000,'point':[0,0]}
        b={'timestamp':1010000000,'point':[3,-4]}
        value=pair_metrics(a,b,.002)
        self.assertEqual(value['speedMps'],1)
        self.assertEqual(value['intervalMs'],10)
        self.assertEqual(value['angleDeg'],53.13)
        self.assertEqual(value['verticalVelocityMps'],.8)

    def test_downward_motion_has_negative_angle(self):
        value=pair_metrics({'timestamp':0,'point':[0,0]}, {'timestamp':10000000,'point':[3,4]},.002)
        self.assertEqual(value['angleDeg'],-53.13)

    def test_invalid_time_cannot_supply_speed(self):
        self.assertIsNone(pair_metrics({'timestamp':1,'point':[0,0]}, {'timestamp':1,'point':[3,4]},.002))
