"""LM1 unchanged-hardware strobe bench, version 0.1.0."""
import json
import time
from pathlib import Path

import cv2
import numpy as np
import serial
from picamera2 import Picamera2

OUT = Path('/home/lm1/strobe-demo-v0.1.0/bench')
OUT.mkdir(parents=True, exist_ok=True)
port = serial.Serial('/dev/ttyACM0', 115200, timeout=0.1, write_timeout=2)
time.sleep(0.5)

def command(line):
    port.reset_input_buffer()
    port.write((line + '\n').encode())
    time.sleep(0.12)
    reply = port.read(4096).decode(errors='replace')
    if 'rejected:' in reply or 'ERR ' in reply:
        raise RuntimeError(reply)
    return reply.strip()

def grab(cam, n=12):
    rows = []
    for i in range(n + 12):
        req = cam.capture_request()
        try:
            raw = req.make_array('raw').view('<u2')[:, :640].copy()
            meta = req.get_metadata()
        finally:
            req.release()
        if i >= 12:
            rows.append(raw.astype(np.float32) / 64)
    return np.mean(rows, axis=0), meta

report = []
try:
    print(command('show'), flush=True)
    command('trig off')
    command('stop')
    command('rate 120')
    command('p 30')
    command('i 1500 2200')
    for index in (0, 1):
        cam = Picamera2(index)
        try:
            cam.configure(cam.create_video_configuration(
                main={'size': (640, 400), 'format': 'YUV420'},
                raw={'size': (640, 400), 'format': 'R10'},
                sensor={'output_size': (640, 400), 'bit_depth': 10},
                controls={'FrameRate': 120, 'AeEnable': False, 'ExposureTime': 100, 'AnalogueGain': 4.0},
                buffer_count=6))
            cam.start()
            command('mode flat')
            flat, meta = grab(cam)
            cv2.imwrite(str(OUT / f'cam{index}-flat.png'), np.clip((flat-16)*2, 0, 255).astype('uint8'))
            circles = cv2.HoughCircles(np.clip((flat-16)*2, 0, 255).astype('uint8'), cv2.HOUGH_GRADIENT,
                                      1.2, 60, param1=80, param2=22, minRadius=12, maxRadius=40)
            candidates = []
            if circles is not None:
                for x, y, r in circles[0]:
                    if x < 340 and y > 90:
                        mask = np.zeros(flat.shape, 'uint8')
                        cv2.circle(mask, (round(x), round(y)), round(r*.65), 1, -1)
                        candidates.append((float(flat[mask>0].mean()), float(x), float(y), float(r), mask>0))
            best = max(candidates, key=lambda c:c[0]) if candidates else None
            print('BALL', index, best[:4] if best else None, flush=True)
            for exposure in (1500, 4000, 8000):
                cam.set_controls({'ExposureTime': exposure, 'AnalogueGain': 4.0})
                command('mode off')
                off, meta = grab(cam)
                for pulse in (30, 60, 100):
                    command(f'p {pulse}')
                    command('mode strobe')
                    on, meta = grab(cam)
                    command('ping')
                    diff = on-off
                    cv2.imwrite(str(OUT / f'cam{index}-e{exposure}-p{pulse}.png'), np.clip((on-16), 0, 255).astype('uint8'))
                    row = {'camera':index, 'requestedExposureUs':exposure, 'pulseUs':pulse,
                           'exposureUs':meta.get('ExposureTime'), 'frameDurationUs':meta.get('FrameDuration'),
                           'ambientP99':float(np.percentile(off,99)), 'flashP99':float(np.percentile(diff,99))}
                    if best:
                        mask = best[4]
                        row.update(ball=list(best[1:4]), ambientBall=float(off[mask].mean()),
                                   flashBall=float(diff[mask].mean()), saturation=float(np.mean(on[mask]>=1000)))
                    report.append(row)
                    print(json.dumps(row), flush=True)
        finally:
            cam.stop()
            cam.close()
finally:
    command('mode flat')
    port.close()
    (OUT/'report.json').write_text(json.dumps(report, indent=2))
