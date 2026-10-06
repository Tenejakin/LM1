"""Strobe club validity tests 0.1.1."""
import unittest
import cv2,numpy as np
from strobe_club import analyze_club,analyze_single_flash

class ClubValidityTests(unittest.TestCase):
    def rows(self,moving=False):
        result=[]
        for i in range(8):
            raw=np.full((400,640),18*64,'uint16')
            if moving and i>=3:
                x=80+(i-3)*35
                cv2.rectangle(raw,(x,267),(x+30,285),160*64,-1)
            result.append({'raw':raw,'meta':{'SensorTimestamp':i*8333000}})
        return result

    def test_empty_scene_has_no_club_measurement(self):
        result=analyze_single_flash(self.rows(),[320,280,25],8*8333000)
        self.assertIsNone(result['clubSpeedMps'])
        self.assertIsNone(result['attackAngleDeg'])

    def test_shaft_alone_does_not_become_a_clubhead(self):
        rows=self.rows()
        for i in range(3,8):
            x=80+(i-3)*35
            cv2.rectangle(rows[i]['raw'],(x,220),(x+2,285),160*64,-1)
        result=analyze_single_flash(rows,[320,280,25],8*8333000)
        self.assertIsNone(result['clubSpeedMps'])

    def test_attached_shaft_does_not_discard_a_visible_head(self):
        rows=self.rows(True)
        for i in range(3,8):
            x=80+(i-3)*35
            cv2.rectangle(rows[i]['raw'],(x+25,220),(x+27,280),160*64,-1)
        result=analyze_single_flash(rows,[320,280,25],8*8333000)
        self.assertAlmostEqual(result['clubSpeedMps'],3.58,delta=.15)
        self.assertIsNone(result['attackAngleDeg'])

    def test_uniform_preimpact_head_track_has_only_projected_speed(self):
        result=analyze_single_flash(self.rows(True),[320,280,25],8*8333000)
        self.assertEqual(result['status'],'experimental image-plane estimate')
        self.assertAlmostEqual(result['clubSpeedMps'],3.58,delta=.15)
        self.assertIsNone(result['attackAngleDeg'])

    def test_post_departure_motion_cannot_supply_club_speed(self):
        result=analyze_single_flash(self.rows(True),[320,280,25],3*8333000)
        self.assertIsNone(result['clubSpeedMps'])

    def test_multiflash_evidence_does_not_become_club_speed(self):
        result=analyze_club(self.rows(True),[320,280,25],8*8333000)
        self.assertIsNone(result['clubSpeedMps'])
        self.assertIsNone(result['attackAngleDeg'])
