"""Shaft-guided feature regression 0.1.0: known translation and saved-shot failure."""
import json,math
from pathlib import Path
import tempfile
import unittest
import cv2,numpy as np
from shaft_head_review import review
from app_bridge import convert

class HeadFeatureTests(unittest.TestCase):
    def synthetic(self,folder,stationary=False):
        root=Path(folder);metadata=[];candidates=[]
        for j in (0,1):(root/f'cam{j}').mkdir()
        for i in range(5):
            image=np.full((400,640),18*64,dtype='uint16')
            if i in (2,3):
                dx=0 if stationary else (i-2)*40;dy=0 if stationary else (i-2)*3
                # Texture, broad head and a thin shaft: the shaft must not move
                # the centroid or become the template by itself.
                cv2.rectangle(image,(70+dx,220+dy),(110+dx,240+dy),90*64,-1)
                cv2.rectangle(image,(78+dx,224+dy),(87+dx,235+dy),160*64,-1)
                cv2.line(image,(115+dx,145),(110+dx,220+dy),160*64,2)
                candidates.append(dict(frame=i,shaftSegments=[[115+dx,145,110+dx,220+dy]]))
            for j in (0,1):cv2.imwrite(str(root/f'cam{j}'/f'raw-{i:03}.png'),image)
            metadata.append(dict(frame=i,SensorTimestamp=i*8333000))
        summary=dict(version='0.9.1',triggerSensorTimestamp=4*8333000,
            ballReferences=[[300,220,25],[300,220,25]],cameras=[dict(camera=j,metadata=metadata,
                clubAnalysis=dict(candidateFrames=candidates)) for j in (0,1)])
        (root/'summary.json').write_text(json.dumps(summary))
        return root

    def test_known_textured_head_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            result=review(self.synthetic(folder))
        self.assertEqual(len(result['pairs']),1)
        pair=result['pairs'][0]
        expected=math.hypot(40,3)*.04267/50/.008333
        self.assertAlmostEqual(pair['speedMps'],expected,places=3)
        self.assertAlmostEqual(pair['angleDeg'],math.degrees(math.atan2(-3,40)),places=3)
        self.assertGreater(pair['templateScore'],.9)

    def test_stationary_club_is_not_a_speed_measurement(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(review(self.synthetic(folder,stationary=True))['pairs'],[])

    @unittest.skipUnless(Path('/home/lm1/strobe-demo-v0.6.0/captures/capture-1790899627631206711').exists(),'Saved Pi shot required')
    def test_latest_missing_shot_has_matched_feature_and_forwards_values(self):
        root=Path('/home/lm1/strobe-demo-v0.6.0/captures/capture-1790899627631206711')
        record=json.loads((root/'review.json').read_text());record['shaftHead']=review(root)
        pair=record['shaftHead']['pairs'][-1]
        self.assertGreater(pair['templateScore'],.9)
        self.assertAlmostEqual(pair['speedMps'],6.294,places=2)
        with tempfile.TemporaryDirectory() as folder:
            result=convert(root,record,Path(folder))
        metrics=result['measurements']['metrics']
        self.assertAlmostEqual(metrics['clubSpeedMps']['value'],pair['speedMps'])
        self.assertEqual(metrics['attackAngleDeg']['value'],0)
        self.assertIsNotNone(metrics['smashFactor']['value'])
        self.assertEqual(metrics['clubSpeedMps']['confidence'],.25)
        self.assertIsNone(metrics['spinRpm']['value'])
        self.assertIsNone(metrics['clubPathDeg']['value'])

if __name__=='__main__':unittest.main()
