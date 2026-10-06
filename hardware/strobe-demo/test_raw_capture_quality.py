"""Capture quality regression 0.1.0: gaps, raw clipping and recorded pulse widths."""
import json
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from raw_capture_quality import analyze
from stereo_flash_review import flash_pairs
from launch_angle_review import review as ball_review

class QualityTests(unittest.TestCase):
    def test_short_pulse_fits_where_old_pulse_does_not(self):
        primary=[dict(frame=0,SensorTimestamp=0,ExposureTime=1491)]
        secondary=[dict(frame=0,SensorTimestamp=0,ExposureTime=1200)]
        self.assertEqual(len(flash_pairs(primary,secondary,pulse_us=150)),1)
        self.assertEqual(len(flash_pairs(primary,secondary,pulse_us=250)),0)
        self.assertAlmostEqual(flash_pairs(primary,secondary,pulse_us=150)[0][2],.001075)

    def test_saved_raw_quality_detects_gap_and_clipping(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cameras=[]
            for j in (0,1):
                (root/f'cam{j}').mkdir();metadata=[]
                for i,t in enumerate((0,5000000,10000000,20000000)):
                    metadata.append(dict(frame=i,SensorTimestamp=t,ExposureTime=1491 if j==0 else 4750))
                    raw=np.full((32,32),1023*64 if j==0 else 400*64,dtype='uint16')
                    cv2.imwrite(str(root/f'cam{j}'/f'raw-{i:03}.png'),raw)
                cameras.append(dict(camera=j,metadata=metadata))
            (root/'summary.json').write_text(json.dumps(dict(pattern=dict(rateHz=200,periodUs=5000,pulseUs=150),
                triggerSensorTimestamp=10000000,ballReferences=[[16,16,8]]*2,cameras=cameras)))
            result=analyze(root)
            self.assertEqual(result['inferredSharedFlashPairs'],4)
            self.assertEqual(result['cameras'][0]['observedFps'],200)
            self.assertEqual(result['cameras'][0]['timingGaps'],1)
            self.assertEqual(result['cameras'][0]['preDepartureFrames'],2)
            self.assertEqual(result['cameras'][0]['ballCore'][0]['clippedFraction'],1)
            self.assertEqual(result['cameras'][1]['ballCore'][0]['clippedFraction'],0)
            self.assertEqual(result['cameras'][1]['ballCore'][0]['medianCounts'],400)
            self.assertEqual(ball_review(root)['fits'],[]) # No ball must not crash the review or invent a shot.

if __name__=='__main__':unittest.main()
