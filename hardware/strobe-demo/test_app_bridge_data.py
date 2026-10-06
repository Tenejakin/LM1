"""Real-shot adapter regression 0.1.0; no hardware access."""
import json
from pathlib import Path
import tempfile
import unittest
from app_bridge import convert
from stereo_flash_review import review as stereo_review

SHOT=Path('/home/lm1/strobe-demo-v0.6.0/captures/capture-1790898943937918263')

@unittest.skipUnless(SHOT.exists(),'Real test capture on Pi required')
class AdapterTests(unittest.TestCase):
    def test_real_shot_forwards_provisional_club_values_without_inventing_path(self):
        record=json.loads((SHOT/'review.json').read_text())
        record['stereoFlash']=stereo_review(SHOT,record['ball'])
        with tempfile.TemporaryDirectory() as folder:
            result=convert(SHOT,record,Path(folder))
        metrics=result['measurements']['metrics']
        self.assertAlmostEqual(metrics['clubSpeedMps']['value'],4.01,places=2)
        self.assertAlmostEqual(metrics['attackAngleDeg']['value'],-4.44,places=2)
        self.assertAlmostEqual(metrics['smashFactor']['value'],metrics['ballSpeedMps']['value']/4.01,places=5)
        self.assertEqual(metrics['clubSpeedMps']['status'],'estimated')
        self.assertEqual(metrics['clubSpeedMps']['confidence'],.15)
        self.assertIn('unverified',metrics['clubSpeedMps']['reason'])
        self.assertIsNone(metrics['clubPathDeg']['value'])
        self.assertIsNone(metrics['spinRpm']['value'])
        self.assertLess(metrics['startDirectionDeg']['value'],0)
        self.assertEqual(metrics['startDirectionDeg']['confidence'],.2)
        self.assertIn('direction sign',metrics['startDirectionDeg']['reason'])
        self.assertEqual(result['id'],SHOT.name)

if __name__=='__main__':unittest.main()
