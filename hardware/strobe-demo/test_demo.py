"""Timing, frame tracking and rejection tests for prototype 0.3.1."""
import math
import unittest
import tempfile
import json
from pathlib import Path
import demo
import cv2
import numpy as np

from demo import BALL_MM, CODED_PATTERN as PATTERN, ball_present, fit_copies, frame_track, reference_similarity, locate_ball, analyze_frames, result_points_for_frame


class FlashTimingTests(unittest.TestCase):
    def test_accepted_copy_capture_saves_summary_and_preview(self):
        background=np.full((400,640),18*64,dtype='uint16')
        shot=background.copy()
        for centre in ((388,235),(424,214),(477,185)):
            cv2.circle(shot,centre,24,200*64,-1)
        with tempfile.TemporaryDirectory() as folder:
            instance=demo.Demo(Path(folder))
            instance.ball=[[286,289,25],[286,289,25]]
            instance.trigger_ns=0
            for j in (0,1):
                instance.rows[j].extend({'raw':image,'meta':{'SensorTimestamp':i*20000000,'ExposureTime':8000,'AnalogueGain':1.}} for i,image in enumerate([shot]+[background]*6))
            old_mode,old_pattern=demo.COPY_MODE,demo.PATTERN
            try:
                demo.COPY_MODE=True
                demo.PATTERN={'periodUs':20000,'gapsUs':[5000,8000]}
                instance.save_capture()
            finally:demo.COPY_MODE, demo.PATTERN=old_mode,old_pattern
            saved=next(Path(folder).glob('capture-*'))
            summary=json.loads((saved/'summary.json').read_text())
            self.assertTrue(summary['cameras'][0]['analysis']['best']['accepted'])
            self.assertTrue((saved/'contact.jpg').is_file())
            self.assertEqual(instance.state,'waiting for stationary ball')

    def test_preview_draws_all_copies_only_in_their_frame(self):
        fit={'frame':4,'points':[[100,100],[140,90],[200,75]]}
        self.assertEqual(result_points_for_frame(fit,4),fit['points'])
        self.assertEqual(result_points_for_frame(fit,3),[])

    def test_preview_draws_one_track_point_per_frame(self):
        fit={'frames':[3,4,5],'points':[[100,100],[140,90],[200,75]]}
        self.assertEqual(result_points_for_frame(fit,4),[[140,90]])
        self.assertEqual(result_points_for_frame(fit,2),[])
        self.assertEqual(result_points_for_frame(None,4),[])

    def test_touching_flash_copies_can_be_resolved(self):
        background=np.full((400,640),18*64,dtype='uint16')
        shot=background.copy()
        for centre in ((388,235),(424,214),(477,185)):
            cv2.circle(shot,centre,24,200*64,-1)
        rows=[{'raw':image,'meta':{'SensorTimestamp':i*20000000}} for i,image in enumerate([shot]+[background]*6)]
        result=analyze_frames(rows,[286,289,25],{'periodUs':20000,'gapsUs':[5000,8000]})
        self.assertIsNotNone(result['best'])
        self.assertEqual(result['best']['copies'],3)
        self.assertAlmostEqual(result['best']['speedMps'],6.6,delta=.5)

    def test_empty_night_frames_do_not_produce_a_measurement(self):
        background=np.full((400,640),18*64,dtype='uint16')
        rows=[{'raw':background,'meta':{'SensorTimestamp':i*20000000}} for i in range(6)]
        self.assertIsNone(analyze_frames(rows,[286,289,25],{'periodUs':20000,'gapsUs':[5000,8000]})['best'])

    def test_dim_ball_can_arm_microburst_but_empty_mat_cannot(self):
        raw=np.full((400,640),18*64,dtype='uint16')
        self.assertFalse(ball_present(raw,[322,290,28],3))
        cv2.circle(raw,(322,290),28,24*64,-1)
        self.assertTrue(ball_present(raw,[322,290,28],3))
        self.assertFalse(ball_present(raw,[322,290,28]))

    def test_new_copy_pattern_identifies_all_cyclic_phases(self):
        pattern={'periodUs':20000,'gapsUs':[5000,8000]}
        gaps=[5000,8000,7000]
        for phase in range(3):
            times=np.array([0,gaps[phase],gaps[phase]+gaps[(phase+1)%3]])/1e6
            points=np.column_stack((300+times*10*1000*48/BALL_MM,200-times*2*1000*48/BALL_MM))
            fit=fit_copies(points,48,pattern)
            self.assertTrue(fit['accepted'],fit)
            self.assertEqual(fit['phase'],phase)
            self.assertAlmostEqual(fit['speedMps'],math.hypot(10,2),delta=.01)

    def test_resting_ball_is_located_away_from_previous_placement(self):
        raw=np.full((400,640),40*64,dtype='uint16')
        cv2.circle(raw,(226,265),24,300*64,-1)
        located=locate_ball(raw,[253,265,24])
        self.assertIsNotNone(located)
        self.assertAlmostEqual(located[0],226,delta=2)
        self.assertAlmostEqual(located[1],265,delta=2)
        self.assertAlmostEqual(located[2],24,delta=2)

    def make_rows(self,other_origin=False,exposure=500):
        rows=[]
        for i in range(18):
            raw=np.full((400,640),40*64,dtype='uint16')
            if i<5:cv2.circle(raw,(253,265),24,300*64,-1)
            elif i<13:cv2.circle(raw,(300+(i-5)*30,(120 if other_origin else 240)-(i-5)*8),24,300*64,-1)
            rows.append({'raw':raw,'meta':{'SensorTimestamp':int(i*4_132_000),'ExposureTime':exposure}})
        return rows

    def test_short_exposure_track_recovers_sensor_timed_speed(self):
        result=frame_track(self.make_rows(),[253,265,24])
        self.assertIsNotNone(result['best'],result)
        expected=math.hypot(30,8)*BALL_MM/48/4.132
        self.assertAlmostEqual(result['best']['speedMps'],expected,delta=.05)
        self.assertGreaterEqual(result['best']['samples'],6)

    def test_ball_is_tracked_through_bright_dark_background_transition(self):
        rows=self.make_rows(exposure=250)
        for i,row in enumerate(rows):
            raw=np.full((400,640),40*64,dtype='uint16')
            raw[:,420:]=500*64
            if i<5:cv2.circle(raw,(253,265),24,300*64,-1)
            elif i<13:cv2.circle(raw,(300+(i-5)*30,240-(i-5)*8),24,300*64,-1)
            row['raw']=raw
        result=frame_track(rows,[253,265,24])
        self.assertIsNotNone(result['best'],result)
        self.assertGreaterEqual(result['best']['samples'],7)
        self.assertIn('dark',result['best']['polarities'])
        self.assertIn('bright',result['best']['polarities'])

    def test_static_dark_circle_does_not_generate_a_track(self):
        rows=self.make_rows(exposure=250)
        for row in rows:
            row['raw']=np.full((400,640),400*64,dtype='uint16')
            cv2.circle(row['raw'],(360,200),24,40*64,-1)
        self.assertIsNone(frame_track(rows,[253,265,24])['best'])

    def test_object_originating_elsewhere_is_not_a_ball_track(self):
        self.assertIsNone(frame_track(self.make_rows(other_origin=True),[253,265,24])['best'])

    def test_long_exposure_smears_are_not_relabelled_as_short_exposure_measurements(self):
        self.assertIsNone(frame_track(self.make_rows(exposure=8000),[253,265,24])['best'])

    def test_brightness_variation_does_not_fake_departure(self):
        raw=np.full((400,640),40*64,dtype='uint16')
        cv2.circle(raw,(253,265),24,300*64,-1)
        self.assertGreater(reference_similarity(raw//2,raw,[253,265,24]),.99)
        empty=np.full_like(raw,40*64)
        self.assertLess(reference_similarity(empty,raw,[253,265,24]),.8)

    def test_empty_bright_mat_cannot_arm(self):
        raw=np.full((400,640),300*64,dtype='uint16')
        self.assertFalse(ball_present(raw,[250,260,24]))
        cv2.circle(raw,(250,260),24,900*64,-1)
        self.assertTrue(ball_present(raw,[250,260,24]))

    def test_hand_adjacent_to_ball_blocks_arming(self):
        raw=np.full((400,640),40*64,dtype='uint16')
        cv2.circle(raw,(250,260),24,300*64,-1)
        cv2.rectangle(raw,(212,220),(244,300),280*64,-1)
        self.assertFalse(ball_present(raw,[250,260,24]))

    def test_each_flash_phase_recovers_speed_without_club_prior(self):
        gaps=PATTERN['gapsUs']+[PATTERN['periodUs']-sum(PATTERN['gapsUs'])]
        for phase in range(3):
            for speed in (20,35,50):
                times=[0,gaps[phase],gaps[phase]+gaps[(phase+1)%3]]
                points=[[100+speed*t/1000*48/BALL_MM*math.cos(.3),300-speed*t/1000*48/BALL_MM*math.sin(.3)] for t in times]
                result=fit_copies(points,48)
                self.assertTrue(result['accepted'],result)
                self.assertAlmostEqual(result['speedMps'],speed,delta=.01)
                self.assertEqual(result['phase'],phase)

    def test_two_copies_cannot_identify_flash_phase(self):
        self.assertIsNone(fit_copies([[100,200],[180,180]],48))

    def test_nearly_equal_gaps_are_rejected_as_ambiguous(self):
        pattern={'gapsUs':[2000,2020],'periodUs':6060}
        result=fit_copies([[100,200],[180,180],[260,160]],48,pattern)
        self.assertFalse(result['accepted'])
        self.assertTrue(result['ambiguous'])

    def test_inconsistent_row_is_rejected(self):
        result=fit_copies([[100,200],[180,110],[260,200]],48)
        self.assertTrue(result is None or not result['accepted'])


if __name__=='__main__':unittest.main()
