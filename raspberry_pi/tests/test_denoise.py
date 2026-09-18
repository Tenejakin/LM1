import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ball_detector import denoise_analysis_frames

class DenoiseTests(unittest.TestCase):
    def test_noise_reduced_without_temporal_ghosts_or_source_changes(self):
        rng = np.random.default_rng(8)
        images = []
        for cx in (25, 65):
            clean = np.full((90, 90), 30, np.uint8)
            cv2.circle(clean, (cx, 45), 12, 190, -1)
            images.append(np.clip(clean.astype(float) + rng.normal(0, 4, clean.shape), 0, 255).astype(np.uint8))
        originals = [im.copy() for im in images]
        with patch.dict(os.environ, {'PINPOINT_ANALYSIS_DENOISE': 'bilateral'}):
            result, reference = denoise_analysis_frames([(1.,images[0]), (2.,images[1])], images[0])
        self.assertEqual([t for t,_ in result], [1.,2.])
        for i,(_,im) in enumerate(result):
            np.testing.assert_array_equal(images[i], originals[i])
            self.assertLess(im[:15,:15].std(), images[i][:15,:15].std())
            cx = (25,65)[i]
            self.assertGreater(int(im[45,cx]), 170)
            self.assertLess(int(im[45,(65,25)[i]]), 50)
        np.testing.assert_array_equal(reference, result[0][1])

    def test_off_and_invalid_modes(self):
        frames = [(1.,np.zeros((10,10),np.uint8))]
        with patch.dict(os.environ, {'PINPOINT_ANALYSIS_DENOISE':'none'}):
            self.assertIs(denoise_analysis_frames(frames)[0], frames)
        with patch.dict(os.environ, {'PINPOINT_ANALYSIS_DENOISE':'invalid'}):
            with self.assertRaises(ValueError):
                denoise_analysis_frames(frames)
