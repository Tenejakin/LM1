#!/usr/bin/env python3
"""Bench test for the LM1 strobe: do the flashes land inside the camera exposure?

Run on the Pi with the ESP32 running strobe_master.ino. Stop the pinpoint
service first so the camera is free:  sudo systemctl stop pinpoint

Examples
  # ESP32 on USB: compares frames with the light off and on, then saves images
  python3 strobe_capture_test.py --serial /dev/ttyACM0

  # No serial link: just saves frames so you can look at them (toggle the ESP32 by hand)
  python3 strobe_capture_test.py --frames 10

The camera free-runs (no TRIG wire). The defaults are 640x400 at 242 fps with a
4000 us exposure and the ESP32 "driver" preset.

Use a DARK room, or cover the lens with an IR-pass filter. Long exposures let
ambient light in, which hides the flashes. Put a small ball (or anything
shiny) in view, wave it through, and look at the saved *_on_*.png files: each
flash should leave a separate copy of the moving object.
"""
import argparse
import os
import time

import cv2
import numpy as np
from picamera2 import Picamera2


def open_serial(path):
    try:
        import serial  # pyserial: sudo apt install python3-serial
    except ImportError:
        raise SystemExit("pyserial is missing: sudo apt install python3-serial")
    port = serial.Serial(path, 115200, timeout=0.3)
    time.sleep(0.5)
    port.reset_input_buffer()
    return port


def send(port, line):
    if port is None:
        return ""
    port.write((line + "\n").encode())
    time.sleep(0.25)
    reply = port.read(port.in_waiting or 1).decode(errors="replace")
    return reply.strip()


def grab(camera, count, settle=10):
    """Return `count` grayscale frames after discarding `settle` frames."""
    for _ in range(settle):
        camera.capture_array()
    frames = []
    for _ in range(count):
        frame = camera.capture_array()
        frames.append(frame if frame.ndim == 2 else frame.mean(axis=2).astype(np.uint8))
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=400)
    ap.add_argument("--fps", type=float, default=242, help="camera frame rate (640x400 runs at 242)")
    ap.add_argument("--exposure-us", type=int, default=4000,
                    help="close to the frame period so every burst lands in an exposure")
    ap.add_argument("--preset", default="driver", choices=["driver", "iron"],
                    help="ESP32 flash preset sent when --serial is used")
    ap.add_argument("--gain", type=float, default=1.0)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--serial", help="ESP32 serial port, e.g. /dev/ttyACM0")
    ap.add_argument("--out", default="strobe_test_out")
    ap.add_argument("--min-delta", type=float, default=1.0,
                    help="mean brightness increase (0-255) needed to call the flashes visible")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    port = open_serial(args.serial) if args.serial else None

    camera = Picamera2(args.camera)
    config = camera.create_video_configuration(
        main={"size": (args.width, args.height), "format": "RGB888"},
        sensor={"output_size": (args.width, args.height), "bit_depth": 10},
        controls={"FrameRate": args.fps, "AeEnable": False,
                  "ExposureTime": args.exposure_us, "AnalogueGain": args.gain},
        buffer_count=6,
    )
    camera.configure(config)
    camera.start()
    time.sleep(0.5)
    meta = camera.capture_metadata()
    print(f"camera {args.camera}: exposure {meta.get('ExposureTime')} us, "
          f"frame duration {meta.get('FrameDuration')} us, gain {meta.get('AnalogueGain')}")

    if port is not None:
        frame_us = meta.get("FrameDuration") or int(1e6 / args.fps)
        print("ESP32 <- preset:", send(port, f"preset {args.preset}").splitlines()[:1])
        print("ESP32 <- rate:", send(port, f"rate {round(1e6 / frame_us)}").splitlines()[:1])

    results = {}
    try:
        for label, command in (("off", "light off"), ("on", "light on")):
            reply = send(port, command)
            if port is not None:
                print(f"ESP32 <- {command!r}: {reply.splitlines()[0] if reply else 'no reply'}")
            elif label == "on":
                print("No serial link: make sure the ESP32 is flashing now.")
            frames = grab(camera, args.frames)
            means = [float(f.mean()) for f in frames]
            results[label] = float(np.mean(means))
            best = int(np.argmax([f.max() for f in frames]))
            cv2.imwrite(os.path.join(args.out, f"{label}_{args.exposure_us}us.png"), frames[best])
            for index in range(min(3, len(frames))):
                cv2.imwrite(os.path.join(args.out, f"{label}_{index}.png"), frames[index])
            print(f"light {label:>3}: mean brightness {results[label]:6.2f} "
                  f"(frame-to-frame spread {np.std(means):.2f})")
    finally:
        send(port, "light on")
        camera.stop()
        camera.close()

    if port is not None:
        delta = results["on"] - results["off"]
        print(f"\nflash adds {delta:+.2f} grey levels on average")
        if delta >= args.min_delta:
            print("PASS: flashes land inside the exposure.")
        else:
            print("NOT SEEN: no brightness change. Check the IR ring is facing the scene, the room is dark,\n"
                  "the camera has no IR-cut filter, and try a longer --exposure-us or a different 'd' delay.")
    print(f"images saved in {args.out}/")


if __name__ == "__main__":
    main()
