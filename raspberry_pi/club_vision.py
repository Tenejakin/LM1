"""Tag-free clubhead measurement from the moving silhouette.

Without an AprilTag on the club there is no PnP scale, so nothing here can solve
depth on its own. Every value imports scale from geometry that is already known:
the calibrated ground plane, the ball's known radius, and -- for face contact --
an optional per-club face size the user measures once. Each result names the
assumption carrying it, and anything that cannot be supported is left unavailable
rather than filled from a club profile.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

try:
    import cv2
    import numpy as np
except ModuleNotFoundError:  # The BLE service can still run without camera support.
    cv2 = None
    np = None

# A clubhead stands roughly 1.2 ball diameters tall in these images; the shaft
# continues well above it, so a band this deep from the lowest silhouette point
# isolates the head without segmenting the two apart.
HEAD_BAND_BALL_RADII = 2.4
MIN_HEAD_POINTS = 8
MIN_SHAFT_POINTS = 25
MIN_SHAFT_EXTENT_PX = 30.0
MIN_HEAD_AREA_PX = 60.0
# On the stand the head enters the view only 4-5 frames before impact: the first is
# clipped by the image edge and the last merges with the ball, leaving three clean
# frames. Replaying 15 real chips (2026-09-24) at three frames recovered club speed
# on 13 instead of 7, agreeing with the 4+ frame values; fit residual still gates it.
MIN_TRACK_FRAMES = 3
MAX_TRACK_FRAMES = 10
# Accepted frames before a tag-free club speed can be graded as measured.
MEASURED_TRACK_FRAMES = 8
# Above any real club's ball/club speed ratio (a driver at the COR limit reaches ~1.5):
# the club track, not the ball, is wrong.
MAX_PLAUSIBLE_SMASH = 1.55
# Below this the club track, not the strike, is wrong: even a heavy mishit keeps
# ball speed above ~0.7 of club speed with a lofted club.
MIN_PLAUSIBLE_SMASH = 0.7
# Attack angles beyond these are tracking errors (a -37 deg chip came from a bad
# single-camera track on 2026-09-25); real ones sit within about -15..+10 deg.
MIN_PLAUSIBLE_ATTACK_DEG = -25.0
MAX_PLAUSIBLE_ATTACK_DEG = 15.0


def implausible_club(speed_mps, ball_speed_mps, attack_deg):
    """Why a club track cannot be right, or None."""
    if not MIN_PLAUSIBLE_ATTACK_DEG <= attack_deg <= MAX_PLAUSIBLE_ATTACK_DEG:
        return (f"Club attack angle {attack_deg:.0f}° is outside {MIN_PLAUSIBLE_ATTACK_DEG:.0f}..{MAX_PLAUSIBLE_ATTACK_DEG:.0f}°; "
                "the club track is wrong.")
    if isinstance(ball_speed_mps, (int, float)) and math.isfinite(ball_speed_mps) and speed_mps > 0:
        smash = ball_speed_mps / speed_mps
        if not MIN_PLAUSIBLE_SMASH <= smash <= MAX_PLAUSIBLE_SMASH:
            return (f"Club speed {speed_mps:.1f} m/s with ball speed {ball_speed_mps:.1f} m/s gives smash {smash:.2f}, "
                    f"outside {MIN_PLAUSIBLE_SMASH}-{MAX_PLAUSIBLE_SMASH} for any real strike; the club track is wrong.")
    return None
# Silhouette centroids are a softer feature than a tag corner; the ball path's
# 8 mm gate would reject nearly every real swing.
MAX_CLUB_FIT_RESIDUAL_M = 0.02
MAX_HEAD_AREA_DEVIATION = 0.35
MIN_CLUB_SPEED_MPS = 1.0
MAX_CLUB_SPEED_MPS = 80.0
MIN_FACE_WIDTH_MM = 55.0
MAX_FACE_WIDTH_MM = 135.0
MIN_FACE_HEIGHT_MM = 20.0
MAX_FACE_HEIGHT_MM = 80.0
# sin of the angle between the ray and the swing plane. Below this the camera is
# looking along the swing instead of across it and depth stops being observable.
MIN_PLANE_INCIDENCE = 0.15


def to_gray(frame):
    return frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def motion_mask(frame, background, close=5):
    """Difference mask of whatever moved, corrected for mains-frequency lamp flicker.

    Shared with the ball path so both see the same silhouette: a club that clips
    the ball's disc clips the same pixels the ball detector rejected.
    """
    gray = to_gray(frame)
    gain = float(background.mean()) / max(float(gray.mean()), 1.0)
    gray = np.clip(gray.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    diff = cv2.subtract(gray, background)
    threshold, _ = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Otsu returns 0 for a noise-free frame whose only change is one small blob, and
    # splits sensor noise on a frame where nothing moved; floor it at a real difference.
    _, mask = cv2.threshold(diff, max(threshold, 20), 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    if close:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close, close)))
    return mask


# A pixel that differs from the pre-shot background in this share of the frames before
# impact is a persistent offset (a shoe that shifted), not the club passing through.
PERSISTENT_CHANGE_FRACTION = 0.6
PERSISTENT_CHANGE_THRESHOLD = 25


def persistent_change(frames, background):
    """Mask of pixels changed in most of ``frames``: things that moved and stayed, never the club.

    On 2026-09-25 a white shoe that shifted slightly differed from the background in every
    frame; both club trackers followed it as a perfectly steady "club" at 0.0 m/s.
    """
    if len(frames) < 5:
        return None
    count = np.zeros(background.shape, np.uint16)
    for frame in frames:
        count += cv2.absdiff(to_gray(frame), background) >= PERSISTENT_CHANGE_THRESHOLD
    mask = (count >= PERSISTENT_CHANGE_FRACTION * len(frames)).astype(np.uint8) * 255
    return cv2.dilate(mask, np.ones((5, 5), np.uint8))


def club_silhouette(frame, background, ball_pixel, ball_radius_px, ignore=None):
    """Largest moving blob that is not the resting ball: the clubhead with its shaft."""
    mask = motion_mask(frame, background, close=7)
    if ignore is not None:
        mask[ignore > 0] = 0
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    best = None
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < MIN_HEAD_AREA_PX:
            continue
        points = contour.reshape(-1, 2).astype(float)
        # The resting ball cancels in the median background, so a ball-sized blob
        # centred on the ball is a detection residual, not the club.
        if (np.linalg.norm(points.mean(axis=0) - ball_pixel) < ball_radius_px
                and area < math.pi * (ball_radius_px * 1.6) ** 2):
            continue
        if best is None or area > best[0]:
            best = (area, points)
    return None if best is None else best[1]


def head_points(points, ball_radius_px):
    """The blob's lowest band: the clubhead, with the shaft above it discarded."""
    band = HEAD_BAND_BALL_RADII * ball_radius_px
    head = points[points[:, 1] >= points[:, 1].max() - band]
    return head if len(head) >= MIN_HEAD_POINTS else None


def shaft_angle_deg(points, head):
    """Image-space shaft lean from the blob above the head band, measured from vertical.

    A dozen stray points above the head fit a direction that is pure noise, so this
    needs a real length of shaft before it will report anything.
    """
    above = points[points[:, 1] < head[:, 1].min()]
    if len(above) < MIN_SHAFT_POINTS or np.ptp(above[:, 1]) < MIN_SHAFT_EXTENT_PX:
        return None
    centered = above - above.mean(axis=0)
    # The shaft is the dominant elongated structure left once the head is removed.
    direction = np.linalg.svd(centered, full_matrices=False)[2][0]
    if direction[1] > 0:
        direction = -direction
    return math.degrees(math.atan2(direction[0], -direction[1]))


def swing_plane(ball_center, ball_velocity):
    """Vertical plane through the ball holding the ball's outgoing horizontal direction.

    At contact the clubhead is touching the ball and travelling with it, so this is
    the best available stand-in for the swing plane when no club tag fixes depth. A
    square strike makes it a good one; an off-line face turns its error into a cosine
    on club speed, which is why the result stays an estimate.
    """
    horizontal = np.array([ball_velocity[0], ball_velocity[1], 0.0], float)
    if np.linalg.norm(horizontal) < 1e-6:
        raise ValueError("Ball has no horizontal direction to define a swing plane.")
    horizontal /= np.linalg.norm(horizontal)
    normal = np.cross(horizontal, [0.0, 0.0, 1.0])
    return normal / np.linalg.norm(normal), horizontal


def plane_point(pixel, matrix, distortion, rotation, translation, origin_point, normal):
    """Intersect a pixel ray with a world plane. The plane supplies the missing scale.

    A camera looking down the swing plane rather than across it makes this
    arbitrarily ill-conditioned: the ray grazes the plane and a pixel of
    segmentation error becomes an unbounded depth error. Refuse that geometry
    instead of returning a number, because the failure is silent otherwise.
    """
    ray = cv2.undistortPoints(np.asarray(pixel, float).reshape(1, 1, 2), matrix, distortion).reshape(2)
    direction = rotation.T @ np.array([ray[0], ray[1], 1.0])
    direction /= np.linalg.norm(direction)
    camera = rotation.T @ -np.asarray(translation, float)
    incidence = float(normal @ direction)
    if abs(incidence) < MIN_PLANE_INCIDENCE:
        raise ValueError(
            f"The camera views the swing plane at {math.degrees(math.asin(min(1.0, abs(incidence)))):.0f}° "
            f"and cannot resolve clubhead depth against it. Move the camera to look across the swing "
            f"rather than along it.")
    distance = float(normal @ (np.asarray(origin_point, float) - camera)) / incidence
    if distance <= 0:
        raise ValueError("Club ray meets the swing plane behind the camera.")
    return camera + direction * distance


def fit_club_velocity(times, positions):
    """Least-squares constant velocity through the head track, with its own residual gate."""
    times, positions = np.asarray(times, float), np.asarray(positions, float)
    if len(times) < MIN_TRACK_FRAMES or np.any(np.diff(times) <= 0):
        raise ValueError(f"Club track needs at least {MIN_TRACK_FRAMES} frames with increasing sensor timestamps.")
    design = np.column_stack((times - times[0], np.ones(len(times))))
    model = np.linalg.lstsq(design, positions, rcond=None)[0]
    residual = float(np.sqrt(np.mean(np.sum((design @ model - positions) ** 2, axis=1))))
    if residual > MAX_CLUB_FIT_RESIDUAL_M:
        raise ValueError(f"Club track fit error {residual * 1000:.0f} mm exceeds "
                         f"{MAX_CLUB_FIT_RESIDUAL_M * 1000:.0f} mm; the head silhouette is not tracking cleanly.")
    return model[0], residual


def club_head_track(frames, impact_index, background, ball_pixel, ball_radius_px,
                    matrix, distortion, rotation, translation, plane_origin, plane_normal):
    """Back-project the pre-impact head centroid onto the swing plane, frame by frame."""
    samples, shaft = [], []
    window = range(max(0, impact_index - MAX_TRACK_FRAMES), impact_index)
    ignore = persistent_change([frames[index][1] for index in window], background)
    for index in window:
        points = club_silhouette(frames[index][1], background, ball_pixel, ball_radius_px, ignore)
        if points is None:
            continue
        head = head_points(points, ball_radius_px)
        if head is None:
            continue
        angle = shaft_angle_deg(points, head)
        if angle is not None:
            shaft.append(angle)
        try:
            world = plane_point(head.mean(axis=0), matrix, distortion, rotation, translation,
                                plane_origin, plane_normal)
        except ValueError:
            continue
        area = float(cv2.contourArea(cv2.convexHull(head.reshape(-1, 1, 2).astype(np.float32))))
        samples.append({"frameIndex": index, "positionM": world, "areaPx": area,
                        "centroidPx": head.mean(axis=0), "headPx": head})
    return samples, shaft


def stable_samples(samples):
    """Longest consecutive run over which the head silhouette keeps the same character.

    A real head crosses lighting boundaries mid-swing: the segmented area can halve
    from one frame to the next while the head itself is tracking perfectly. That step
    also shifts the centroid, so frames either side of it are not the same feature and
    must not be fitted together. Comparing each frame with its neighbour finds the
    boundary; comparing against a global median just rejects both regimes.
    """
    if len(samples) < 2:
        return samples
    runs, run = [], [samples[0]]
    for previous, sample in zip(samples, samples[1:]):
        step = abs(sample["areaPx"] - previous["areaPx"]) / max(previous["areaPx"], 1.0)
        if sample["frameIndex"] != previous["frameIndex"] + 1 or step > MAX_HEAD_AREA_DEVIATION:
            runs.append(run)
            run = []
        run.append(sample)
    runs.append(run)
    usable = [candidate for candidate in runs if len(candidate) >= MIN_TRACK_FRAMES]
    # Prefer the run nearest impact: that is the one carrying the speed at contact.
    return usable[-1] if usable else max(runs, key=len)


def load_club_profile():
    """Optional per-club face size, measured once by the user. No tag, no mounting."""
    path = Path(os.getenv("PINPOINT_CLUB_PROFILE_PATH", "/var/lib/pinpoint/club-profile.json"))
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(profile, dict) or profile.get("version") != 1:
        return None
    width, height = profile.get("faceWidthMm"), profile.get("faceHeightMm")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (width, height)):
        return None
    if not MIN_FACE_WIDTH_MM <= width <= MAX_FACE_WIDTH_MM:
        return None
    if not MIN_FACE_HEIGHT_MM <= height <= MAX_FACE_HEIGHT_MM:
        return None
    return {"faceWidthMm": float(width), "faceHeightMm": float(height), "clubId": profile.get("clubId")}


def face_contact(head, ball_pixel, ball_radius_px, forward_px, profile):
    """Strike coordinates using the ball itself as the ruler in the contact frame.

    Ball and contact patch sit at the same depth, so the ball's apparent radius
    gives millimetres per pixel locally. The face width is checked against the
    measured silhouette so a profile for the wrong club cannot pass silently.
    """
    if profile is None:
        raise ValueError("Measure the clubface once (heel-toe width and face height) "
                         "and save it as the club profile; no club tag is needed.")
    if ball_radius_px <= 0:
        raise ValueError("Ball radius in the contact frame is not usable as a scale reference.")
    scale = 21.335 / ball_radius_px  # millimetres per pixel at the ball's depth
    across = np.array([-forward_px[1], forward_px[0]], float)
    projected = head @ across
    span = float(projected.max() - projected.min()) * scale
    if not MIN_FACE_WIDTH_MM <= span <= MAX_FACE_WIDTH_MM:
        raise ValueError(f"Measured face span {span:.0f} mm is not a plausible heel-toe width; "
                         "the camera cannot see the face edges from this position.")
    if abs(span - profile["faceWidthMm"]) > profile["faceWidthMm"] * 0.35:
        raise ValueError(f"Measured face span {span:.0f} mm disagrees with the saved "
                         f"{profile['faceWidthMm']:.0f} mm profile; confirm the club in use.")
    center = (projected.max() + projected.min()) / 2
    strike_x = (float(ball_pixel @ across) - center) * scale
    sole = float(head[:, 1].max())
    height_above_sole = (sole - float(ball_pixel[1])) * scale
    strike_y = height_above_sole - profile["faceHeightMm"] / 2
    if abs(strike_x) > profile["faceWidthMm"] / 2 or abs(strike_y) > profile["faceHeightMm"] / 2:
        raise ValueError("Estimated contact point falls outside the clubface; rejecting the geometry.")
    return strike_x, strike_y, span
