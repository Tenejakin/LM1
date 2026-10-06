#!/usr/bin/env python3
"""Bench: how big is the ball in the image, and how bright does each flash make it?

Run on the Pi with the pinpoint service stopped and the ESP32 running strobe_master.
For each camera and resolution it takes frames with the light off and on, builds the
on-minus-off image, finds the ball and reports its diameter in pixels and its
brightness. It also compares two flash widths to show how brightness scales.

  python3 bench_ball_light.py --serial /dev/ttyACM0 --out ~/bench_out
"""
import argparse
import os
import time

import cv2
import numpy as np
from picamera2 import Picamera2


def open_serial(path):
    import serial
    port = serial.Serial(path, 115200, timeout=0.3, write_timeout=3)
    time.sleep(1.0)
    port.reset_input_buffer()
    return port


def send(port, line, wait=0.3):
    port.write((line + "\n").encode())
    time.sleep(wait)
    return port.read(4000).decode(errors="replace").strip()


def gray(frame):
    return frame if frame.ndim == 2 else frame.mean(axis=2).astype(np.uint8)


def grab(camera, count, settle=12):
    for _ in range(settle):
        camera.capture_array()
    return [gray(camera.capture_array()).astype(np.float32) for _ in range(count)]


def find_ball(diff):
    """Largest roundish bright blob in the (blurred, stretched) on-minus-off image."""
    blur = cv2.GaussianBlur(diff, (0, 0), 3)
    top = float(np.percentile(blur, 99.9))
    if top < 1.0:
        return None
    img = np.clip(blur * (255.0 / top), 0, 255).astype(np.uint8)
    _, mask = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 80:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        roundness = area / (np.pi * radius * radius + 1e-6)
        score = area * roundness
        if best is None or score > best[0]:
            best = (score, cx, cy, radius, roundness, mask, contour)
    return best


def roi_stats(diff, on_mean, centre, radius):
    mask = np.zeros(diff.shape, np.uint8)
    cv2.circle(mask, (int(centre[0]), int(centre[1])), int(radius), 255, -1)
    inside = mask > 0
    ring = (cv2.dilate(mask, np.ones((25, 25), np.uint8)) > 0) & ~inside
    return (float(diff[inside].mean()), float(on_mean[inside].mean()), float(np.mean(on_mean[inside] >= 250)),
            float(diff[ring].mean()))


def measure(camera_index, size, fps, exposure_us, gain, port, out, pulses, ball=None):
    width, height = size
    camera = Picamera2(camera_index)
    config = camera.create_video_configuration(
        main={"size": size, "format": "RGB888"},
        sensor={"output_size": size, "bit_depth": 10},
        controls={"FrameRate": fps, "AeEnable": False, "ExposureTime": exposure_us, "AnalogueGain": gain},
        buffer_count=6,
    )
    camera.configure(config)
    camera.start()
    time.sleep(0.6)
    meta = camera.capture_metadata()
    frame_us = meta.get("FrameDuration") or int(1e6 / fps)
    real_fps = 1e6 / frame_us
    tag = f"cam{camera_index}_{width}x{height}"
    print(f"\n== {tag}: exposure {meta.get('ExposureTime')} us, frame {frame_us} us ({real_fps:.1f} fps), gain {meta.get('AnalogueGain')}")
    send(port, "preset driver")
    send(port, f"rate {round(real_fps)}")
    send(port, "light off")
    off = grab(camera, 16)
    off_mean = np.mean(off, axis=0)
    cv2.imwrite(os.path.join(out, f"{tag}_off.png"), np.clip(off_mean, 0, 255).astype(np.uint8))
    results = []
    for pulse in pulses:
        send(port, f"p {pulse}")
        send(port, "light on")
        on = grab(camera, 16)
        on_mean = np.mean(on, axis=0)
        diff = np.clip(on_mean - off_mean, 0, None)
        if ball is not None:
            scale = width / 640.0
            centre = (ball[0] * scale, ball[1] * scale)
            add, level, sat, around = roi_stats(diff, on_mean, centre, 18 * scale)
            print(f"  pulse {pulse:>3} us: flash adds {add:6.2f} grey on the ball (background ring {around:5.2f}), "
                  f"ball level {level:5.1f}, saturated {sat * 100:4.1f} %, room mean {off_mean.mean():5.1f}")
            results.append((pulse, 0.0, add))
            continue
        found = find_ball(diff)
        if found is None:
            print(f"  pulse {pulse:>3} us: no flash signal found")
            continue
        _, cx, cy, radius, roundness, mask, contour = found
        ball_mask = np.zeros(diff.shape, np.uint8)
        cv2.drawContours(ball_mask, [contour], -1, 255, -1)
        inside = diff[ball_mask > 0]
        sat = float(np.mean(on_mean[ball_mask > 0] >= 250))
        print(f"  pulse {pulse:>3} us: ball {2 * radius:5.1f} px wide at ({cx:.0f},{cy:.0f}), roundness {roundness:.2f}, "
              f"flash adds {inside.mean():6.2f} grey (peak {inside.max():5.1f}), saturated {sat * 100:4.1f} %")
        results.append((pulse, 2 * radius, float(inside.mean())))
        vis = cv2.cvtColor(np.clip(on_mean * (255.0 / max(on_mean.max(), 1)), 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
        cv2.circle(vis, (int(cx), int(cy)), int(radius), (0, 255, 0), 2)
        cv2.imwrite(os.path.join(out, f"{tag}_on_p{pulse}.png"), vis)
    send(port, "light on")
    camera.stop()
    camera.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument("--out", default="bench_out")
    ap.add_argument("--exposure-us", type=int, default=8000)
    ap.add_argument("--gain", type=float, default=1.0)
    ap.add_argument("--ball", help="ball centres in 640x400 coordinates, one per camera: x0,y0;x1,y1")
    ap.add_argument("--only-640", action="store_true", help="skip the 1280x800 runs")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    port = open_serial(args.serial)
    print("ESP32:", send(port, "show").splitlines()[:1])
    summary = []
    try:
        for index in (0, 1):
            modes = [((640, 400), 242, 3900)] if args.only_640 else [((1280, 800), 120, args.exposure_us), ((640, 400), 242, 3900)]
            for size, fps, exposure in modes:
                try:
                    centre = tuple(float(v) for v in args.ball.split(";")[index].split(",")) if args.ball else None
                    summary.append((index, size, measure(index, size, fps, exposure, args.gain, port, args.out, (15, 45), centre)))
                except Exception as error:  # keep going: one camera may be unavailable
                    print(f"  camera {index} {size}: {error}")
    finally:
        send(port, "preset driver")
        send(port, "rate 242")
        send(port, "light on")
    print("\n== summary (ball width in px, flash brightness)")
    for index, size, results in summary:
        for pulse, width, bright in results:
            print(f"  cam{index} {size[0]}x{size[1]} pulse {pulse} us: {width:.1f} px, +{bright:.2f} grey")


if __name__ == "__main__":
    main()
