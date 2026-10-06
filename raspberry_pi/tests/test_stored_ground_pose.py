import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PINPOINT_GROUND_MODE", "tag")  # these tests cover the saved tag pose
from apriltag_calibration import capture_latest_apriltag_calibration, clear_apriltag_calibration, load_apriltag_calibration
from launch_measurements import stored_ground_pose, measure_launch

class StoredGroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.matrix = np.array([[550.,0,320],[0,550.,200],[0,0,1]])
        self.distortion = np.zeros(5)
        self.env = patch.dict(os.environ, {
            'PINPOINT_APRILTAG_CALIBRATION_PATH':str(self.root/'ground.json'),
            'PINPOINT_SECONDARY_APRILTAG_CALIBRATION_PATH':str(self.root/'ground-secondary.json'),
            'PINPOINT_INTRINSICS_PATH':str(self.root/'lens.json'),
            'PINPOINT_SECONDARY_INTRINSICS_PATH':str(self.root/'lens-secondary.json'),
            'PINPOINT_APRILTAG_ID':'0','PINPOINT_APRILTAG_SIZE_MM':'100'})
        self.env.start(); self.addCleanup(self.env.stop)
        (self.root/'lens.json').write_text(json.dumps({'imageSize':[640,400],
            'cameraMatrix':self.matrix.tolist(),'distCoeffs':self.distortion.tolist(),'rmsPx':.1}))
        points=np.array([[0,0,0],[.1,0,0],[.1,.1,0],[0,.1,0]],float)
        corners,_=cv2.projectPoints(points,np.array([2.5,0.,0.]),np.array([-.05,.02,.5]),self.matrix,self.distortion)
        self.detection={'detected':True,'tagId':0,'tagSizeMm':100,'imageSize':[640,400],
                        'corners':(corners.reshape(4,2)/[640,400]).tolist()}

    def test_explicit_calibration_survives_tag_removal_and_disk_reload(self):
        saved=capture_latest_apriltag_calibration({'aprilTag':self.detection})
        self.assertLess(saved['groundPose']['errorPx'],.01)
        pose=stored_ground_pose((640,400),0,.1,self.matrix,self.distortion)
        self.assertEqual(pose['source'],'stored-calibration')
        frames=[(i*.004,np.zeros((400,640),np.uint8)) for i in range(4)]
        with patch('launch_measurements.find_ground_tag_pose',side_effect=AssertionError('Tag must not be required')):
            result=measure_launch(frames,(250,180,40,40),1,'sensor',95)
        self.assertEqual(result['diagnostics']['groundPose']['source'],'stored-calibration')

    def test_changed_lens_and_clear_invalidate(self):
        capture_latest_apriltag_calibration({'aprilTag':self.detection})
        changed=self.matrix.copy(); changed[0,0]+=1
        with self.assertRaisesRegex(ValueError,'differs'):
            stored_ground_pose((640,400),0,.1,changed,self.distortion)
        with self.assertRaisesRegex(ValueError,'differs'):
            stored_ground_pose((320,200),0,.1,self.matrix,self.distortion)
        clear_apriltag_calibration()
        self.assertIsNone(stored_ground_pose((640,400),0,.1,self.matrix,self.distortion))

    def test_bad_capture_cannot_overwrite_good_pose(self):
        capture_latest_apriltag_calibration({'aprilTag':self.detection})
        original=(self.root/'ground.json').read_text()
        bad={**self.detection,'corners':[[0,0]]}
        with self.assertRaises(ValueError):
            capture_latest_apriltag_calibration({'aprilTag':bad})
        self.assertEqual((self.root/'ground.json').read_text(),original)

    def _secondary_detection(self, matrix):
        # Top camera 85 mm above the lower one, seeing the same tag.
        points=np.array([[0,0,0],[.1,0,0],[.1,.1,0],[0,.1,0]],float)
        corners,_=cv2.projectPoints(points,np.array([2.5,0.,0.]),np.array([-.05,-.065,.5]),matrix,self.distortion)
        return {**self.detection,'corners':(corners.reshape(4,2)/[640,400]).tolist()}

    def test_top_camera_saves_its_own_pose_with_its_own_lens(self):
        top=np.array([[560.,0,318],[0,560.,204],[0,0,1]])
        (self.root/'lens-secondary.json').write_text(json.dumps({'imageSize':[640,400],
            'cameraMatrix':top.tolist(),'distCoeffs':self.distortion.tolist(),'rmsPx':.1}))
        diagnostics={'aprilTag':self.detection,'secondaryAprilTag':self._secondary_detection(top)}
        lower=capture_latest_apriltag_calibration(diagnostics)
        upper=capture_latest_apriltag_calibration(diagnostics,'secondary')
        self.assertEqual(upper['camera'],'secondary')
        self.assertEqual(upper['groundPose']['cameraMatrix'],top.tolist())
        self.assertLess(upper['groundPose']['errorPx'],.01)
        self.assertEqual(load_apriltag_calibration('secondary')['groundPose'],upper['groundPose'])
        self.assertEqual(load_apriltag_calibration()['groundPose'],lower['groundPose'])
        clear_apriltag_calibration('secondary')
        self.assertIsNone(load_apriltag_calibration('secondary'))
        self.assertIsNotNone(load_apriltag_calibration())

    def test_top_camera_needs_the_tag_in_its_own_view(self):
        with self.assertRaisesRegex(ValueError,'top camera'):
            capture_latest_apriltag_calibration({'aprilTag':self.detection},'secondary')
        self.assertFalse((self.root/'ground-secondary.json').exists())
