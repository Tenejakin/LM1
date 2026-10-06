"""v1.0.0: how well is a shot measured with the two cameras in step, and half a frame apart?

Pure simulation with this unit's real lenses, stereo pair and rig pose. For each shot type a ball is
placed where the placement model says is best, launched at a typical speed, and observed by both
cameras at 242 fps. The observations are the ball's pixel centres with 0.5 px of noise (the image
residual of real fits) and the fit unknowns are speed, launch angle, direction and contact time,
with the start anchored at the resting ball as the real fit does. The first two frames after
contact are unusable and a ball must be fully inside the image to be seen.

The reported uncertainty is the Cramer-Rao bound from the fit's Jacobian, so it does not depend on
an optimiser converging. Nothing on the Pi is touched.

    python scripts/simulate-stagger.py path/to/calibration-dir
where the directory holds intrinsics.json, intrinsics-secondary.json, active.json and rig.json.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "raspberry_pi"))
import rig_pose  # noqa: E402

RADIUS = 0.021335
PERIOD = 1 / 241.6
NOISE_PX = 0.5
CONTACT_FRAMES = 2
G = np.array([0.0, 0.0, -9.81])
W, H = 640, 400

SHOTS = [
    # name, ball m/s, launch deg, direction deg, ball centre x px in the lower image
    ("chip", 11, 35, 0.0, 200),
    ("pitch", 25, 20, 0.0, 230),
    ("pitching wedge", 38, 28, 0.0, 160),
    ("7-iron", 48, 19, 0.0, 115),
    ("7-iron, 3 deg right", 48, 19, 3.0, 115),
    ("driver", 65, 13, 0.0, 70),
]


def load(directory: Path):
    def lens(name):
        data = json.loads((directory / name).read_text())
        return np.array(data["cameraMatrix"], float), np.array(data["distCoeffs"], float)
    rig = json.loads((directory / "rig.json").read_text())
    stereo = json.loads((directory / "active.json").read_text())
    pose = rig_pose.level_rig_pose(rig)
    lower = (*lens("intrinsics.json"), pose["rotation"], pose["translation"])
    r, t = np.array(stereo["rotation"], float), np.array(stereo["translationM"], float)
    upper = (*lens("intrinsics-secondary.json"), r @ pose["rotation"], r @ pose["translation"] + t)
    return lower, upper


def project(camera, points):
    matrix, distortion, rotation, translation = camera
    points = np.atleast_2d(points)
    cam = (rotation @ points.T).T + translation
    if np.any(cam[:, 2] <= 0.01):
        return np.full((len(points), 2), np.nan)
    rvec = np.zeros(3)
    return cv2.projectPoints(cam.reshape(-1, 1, 3), rvec, np.zeros(3), matrix, distortion)[0].reshape(-1, 2)


def rest_point(lower, x_px, depth_m=0.62):
    """World point on the ball-centre plane whose lower-camera pixel column is x_px, at roughly depth_m."""
    matrix, distortion, rotation, translation = lower
    best = None
    for y in np.arange(0.35, 0.9, 0.005):
        for x in np.arange(-0.5, 0.4, 0.005):
            point = np.array([x, y, RADIUS])
            cam = rotation @ point + translation
            if cam[2] <= 0:
                continue
            score = abs(cam[2] - depth_m) * 4 + abs(project(lower, point)[0][0] - x_px) * 0.01
            if best is None or score < best[0]:
                best = (score, point)
    return best[1]


def velocity(speed, launch_deg, direction_deg):
    """World velocity: +X target, +Y away from the cameras (the golfer's left), +Z up. Positive direction is right."""
    l, d = math.radians(launch_deg), math.radians(direction_deg)
    return speed * np.array([math.cos(l) * math.cos(d), -math.cos(l) * math.sin(d), math.sin(l)])


def position(params, rest, t):
    speed, launch, direction, t_contact = params
    dt = np.maximum(t - t_contact, 0.0)[:, None]
    return rest + velocity(speed, launch, direction) * dt + 0.5 * G * dt ** 2


def observations(cameras, rest, truth, frame_times):
    """Visible observations: list of (camera index, time, pixel) for the truth trajectory."""
    out = []
    speed, launch, direction, t_contact = truth
    for index, times in enumerate(frame_times):
        pts = position(truth, rest, times)
        for time, point in zip(times, pts):
            if time < t_contact + CONTACT_FRAMES * PERIOD:
                continue
            pixel = project(cameras[index], point)[0]
            if not np.all(np.isfinite(pixel)):
                continue
            depth = (cameras[index][2] @ point + cameras[index][3])[2]
            radius_px = cameras[index][0][0, 0] * RADIUS / depth
            if radius_px <= pixel[0] <= W - radius_px and radius_px <= pixel[1] <= H - radius_px:
                out.append((index, time, pixel))
    return out


def predicted(params, cameras, rest, obs):
    times = np.array([o[1] for o in obs])
    pts = position(params, rest, times)
    return np.array([project(cameras[o[0]], p)[0] for o, p in zip(obs, pts)])


def uncertainty(cameras, rest, truth, obs):
    """Standard deviations of speed (% of speed), launch (deg), direction (deg) from the Jacobian."""
    if len({round(o[1], 7) for o in obs}) < 3 or len({o[0] for o in obs}) < 2:
        return None
    base = predicted(truth, cameras, rest, obs)
    steps = np.array([0.02, 0.05, 0.05, 2e-5])
    jac = []
    for i, step in enumerate(steps):
        shifted = np.array(truth, float)
        shifted[i] += step
        jac.append(((predicted(shifted, cameras, rest, obs) - base) / step).ravel())
    jac = np.array(jac).T / NOISE_PX
    information = jac.T @ jac
    if np.linalg.matrix_rank(information, tol=1e-9) < 4:
        return None
    covariance = np.linalg.inv(information)
    sd = np.sqrt(np.diag(covariance))
    return 100 * sd[0] / truth[0], sd[1], sd[2], sd[3] * 1000


def run(directory, trials, seed, ball_x=None):
    lower, upper = load(directory)
    cameras = (lower, upper)
    rng = np.random.default_rng(seed)
    print(f"period {PERIOD * 1000:.3f} ms, {trials} contact phases per case; sigma = 1-sigma fit uncertainty\n")
    print(f"{'shot':<22}{'mode':<11}{'usable frames':>14}{'fittable':>10}{'speed %':>9}{'launch deg':>12}{'dir deg':>9}{'good':>7}")
    for name, speed, launch, direction, x_px in SHOTS:
        rest = rest_point(lower, ball_x if ball_x is not None else x_px)
        for mode in ("in step", "staggered"):
            counts, sigmas = [], []
            for _ in range(trials):
                t_contact = rng.uniform(0, PERIOD) + 0.05
                grid = np.arange(0, 0.4, PERIOD)
                a = grid
                b = grid if mode == "in step" else grid + PERIOD / 2
                truth = (speed, launch, direction, t_contact)
                obs = observations(cameras, rest, truth, (a, b))
                counts.append(len({round(o[1], 7) for o in obs}))
                sigmas.append(uncertainty(cameras, rest, truth, obs))
            good = [s for s in sigmas if s is not None]
            fittable = len(good) / trials
            if good:
                med = np.median(np.array(good), axis=0)
                ok = sum(1 for s in good if s[0] < 3 and s[1] < 2 and s[2] < 3) / trials
                row = f"{med[0]:>9.2f}{med[1]:>12.2f}{med[2]:>9.2f}{ok:>7.0%}"
            else:
                row = f"{'-':>9}{'-':>12}{'-':>9}{0:>7.0%}"
            print(f"{name:<22}{mode:<11}{np.median(counts):>14.0f}{fittable:>10.0%}{row}")
    print("\ngood = speed within 3 %, launch within 2 deg and direction within 3 deg (1-sigma).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--trials", type=int, default=120)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ball-x", type=float, default=None,
                        help="Place every ball at this lower-image column (px), e.g. 40 for the most room ahead (ball-only)")
    args = parser.parse_args()
    run(args.directory, args.trials, args.seed, args.ball_x)
