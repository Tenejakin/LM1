"""Common-flash timing, geometry and two-point tests 0.1.1."""
import unittest
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import cv2
import numpy as np
from stereo_flash_review import flash_pairs, velocity_metrics

class FlashPairTests(unittest.TestCase):
    def test_only_full_flash_inside_both_exposures(self):
        first=[dict(frame=0,SensorTimestamp=0,ExposureTime=1491),
               dict(frame=1,SensorTimestamp=8333000,ExposureTime=1491)]
        second=[dict(frame=0,SensorTimestamp=500000,ExposureTime=8000),
                dict(frame=1,SensorTimestamp=8833000,ExposureTime=8000)]
        pairs=flash_pairs(first,second)
        self.assertEqual([(a['frame'],b['frame']) for a,b,t in pairs],[(0,0),(1,1)])
        self.assertAlmostEqual(pairs[0][2],.001125)
        second[0]['ExposureTime']=600 # clips the 250us flash
        self.assertEqual(len(flash_pairs(first,second)),1)

    def test_old_short_secondary_shutters_miss_flash(self):
        first=[dict(frame=0,SensorTimestamp=0,ExposureTime=1491)]
        second=[dict(frame=0,SensorTimestamp=-2100000,ExposureTime=1491),
                dict(frame=1,SensorTimestamp=2100000,ExposureTime=1491)]
        self.assertEqual(flash_pairs(first,second),[])

    def test_primary_shutter_must_contain_whole_flash(self):
        self.assertEqual(flash_pairs([dict(frame=0,SensorTimestamp=0,ExposureTime=1100)],
                        [dict(frame=0,SensorTimestamp=0,ExposureTime=8000)]),[])

    def test_camera_side_is_right_and_away_is_left(self):
        self.assertGreater(velocity_metrics([5,-1,2])['directionDeg'],0)
        self.assertLess(velocity_metrics([5,1,2])['directionDeg'],0)
        self.assertGreater(velocity_metrics([5,0,2])['angleDeg'],0)
        self.assertLess(velocity_metrics([5,0,-1])['angleDeg'],0)

    @unittest.skipUnless(Path('/var/lib/pinpoint/stereo/active.json').exists(),'Pi stereo calibration required')
    def test_projected_two_view_flight_uses_actual_calibration(self):
        sys.path.insert(0,'/opt/pinpoint')
        from stereo_check import _camera,_project
        from stereo_calibration import fixed_secondary_pose
        from stereo_flash_review import review
        lenses=[json.loads(Path('/var/lib/pinpoint/'+name).read_text())
                for name in ('intrinsics.json','intrinsics-secondary.json')]
        inputs=[(np.array(l['cameraMatrix']),np.array(l['distCoeffs'])) for l in lenses]
        rotation=np.array([[1,0,0],[0,0,-1],[0,1,0]])
        lower_input=(*inputs[0],rotation,np.zeros(3))
        pose=fixed_secondary_pose(lower_input,inputs[1],(640,400),(0,1))
        cameras=[_camera(*lower_input),_camera(*inputs[1],pose['rotation'],pose['translation'])]
        rest=np.array([-.1,.45,-.09]);velocity=np.array([5.,-1.5,2.])
        period=8333000;metadata=[[],[]];track=[]
        pixel=_project(cameras[0],[rest])[0];radius=.021335*inputs[0][0][0,0]/.45
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for j in (0,1):(root/f'cam{j}').mkdir()
            for i in range(6):
                position=rest+velocity*max(0,i-1)*period/1e9
                for j,camera in enumerate(cameras):
                    centre=_project(camera,[position])[0]
                    depth=(camera['R']@position+camera['t'])[2]
                    r=.021335*camera['K'][0,0]/depth
                    raw=np.full((400,640),18*64,dtype='uint16')
                    cv2.circle(raw,tuple(np.round(centre).astype(int)),round(r),818*64,-1)
                    cv2.imwrite(str(root/f'cam{j}'/f'raw-{i:03}.png'),raw)
                    metadata[j].append(dict(frame=i,SensorTimestamp=i*period-(500000 if j else 0),
                                             ExposureTime=8000 if j else 1491))
                    if j==0 and i>=2:track.append(dict(frame=i,point=[*centre,r],timestamp=i*period))
            summary=dict(version='0.9.0',triggerSensorTimestamp=2*period,
                ballReferences=[[*pixel,radius],[*pixel,radius]],cameras=[dict(metadata=m) for m in metadata])
            (root/'summary.json').write_text(json.dumps(summary))
            result=review(root,dict(track=track))
            self.assertIsNotNone(result['ball'])
            self.assertGreater(result['ball']['directionDeg'],0)
            self.assertAlmostEqual(result['ball']['speedMps'],np.linalg.norm(velocity),delta=1.)
            self.assertIsNone(result['club']) # No club in synthetic images: no invented metrics.
            # Known same-feature hosel pixels in only two pre-departure frames:
            # check the low-confidence fallback without relaxing the old tracker.
            error=ValueError('Only two consistent club positions')
            error.diagnostics={'runsByPoint':{'hosel':2,'head':0}}
            club_velocity=np.array([4.,-.5,-.2]);pixels=[]
            for i in (0,1):
                head=rest+np.array([-.12,0,.015])+club_velocity*i*period/1e9
                pixels.extend(_project(camera,[head])[0] for camera in cameras)
            with patch('club_stereo.measure',side_effect=error), \
                 patch('club_stereo.hosel_pixel',side_effect=pixels), \
                 patch('club_stereo.head_pixel',return_value=None):
                result=review(root,dict(track=track))
            self.assertIsNotNone(result['club'],str(result))
            self.assertEqual(result['club']['diagnostics']['acceptedFrames'],2)
            self.assertAlmostEqual(result['club']['speedMps'],np.linalg.norm(club_velocity),delta=.01)
            self.assertLess(result['club']['angleDeg'],0)
            self.assertGreater(result['club']['directionDeg'],0)

if __name__=='__main__':unittest.main()
