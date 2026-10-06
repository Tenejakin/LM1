"""v1.0.0: can the two OV9281 cameras be held half a frame apart?

Run ON the Pi with the pinpoint service stopped (the cameras must be free). Three experiments,
each opening both cameras fresh and timing frames by their sensor timestamps:

  E0  the current libcamera server/client sync, as the service uses it
  E1  free-running, no sync: how fast does the phase between the two sensors drift?
  E2  free-running with a software servo on the second camera's frame duration, steering the
      phase to half a frame and holding it

Nothing is written except the JSON report. Usage:

    sudo systemctl stop pinpoint; /opt/pinpoint/.venv/bin/python scripts/test-stagger-phase.py --seconds 15; sudo systemctl start pinpoint
"""
from __future__ import annotations

import argparse
import bisect
import json
import statistics
import threading
import time

WIDTH, HEIGHT, FPS = 640, 400, 242
EXPOSURE_US, GAIN = 100, 4.0


def open_camera(index, extra_controls=None):
    from picamera2 import Picamera2
    camera = Picamera2(index)
    controls = {"FrameRate": float(FPS), "AeEnable": False, "ExposureTime": EXPOSURE_US, "AnalogueGain": GAIN}
    controls.update(extra_controls or {})
    config = camera.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "RGB888"},
        sensor={"output_size": (WIDTH, HEIGHT), "bit_depth": 10}, controls=controls, buffer_count=8)
    camera.configure(config)
    return camera


class Recorder(threading.Thread):
    """Drain one camera, keeping only sensor timestamps (no image conversion, so it stays cheap)."""

    def __init__(self, camera, on_frame=None):
        super().__init__(daemon=True)
        self.camera, self.on_frame, self.stamps = camera, on_frame, []
        self.stop_event = threading.Event()
        self.error = None

    def run(self):
        try:
            while not self.stop_event.is_set():
                request = self.camera.capture_request(wait=True)
                try:
                    stamp = request.get_metadata().get("SensorTimestamp")
                finally:
                    request.release()
                if stamp:
                    self.stamps.append(int(stamp))
                    if self.on_frame:
                        self.on_frame(int(stamp))
        except Exception as error:  # reported in the summary
            self.error = repr(error)


def phase_series(a_stamps, b_stamps, period_ns):
    """Phase of each B frame after the nearest earlier-or-equal A frame, in microseconds, 0 to period."""
    out = []
    for stamp in b_stamps:
        i = bisect.bisect_right(a_stamps, stamp) - 1
        if i < 0:
            continue
        out.append((stamp, ((stamp - a_stamps[i]) % period_ns) / 1000.0))
    return out


def circular_stats(values_us, period_us):
    """Mean and spread of phases on a circle, so 0 and period count as neighbours."""
    import math
    angles = [2 * math.pi * v / period_us for v in values_us]
    s, c = sum(map(math.sin, angles)) / len(angles), sum(map(math.cos, angles)) / len(angles)
    mean = (math.atan2(s, c) % (2 * math.pi)) * period_us / (2 * math.pi)
    deviations = [((v - mean + period_us / 2) % period_us) - period_us / 2 for v in values_us]
    return mean, statistics.pstdev(deviations), max(abs(d) for d in deviations)


def intervals(stamps):
    return [(b - a) / 1000.0 for a, b in zip(stamps, stamps[1:])]


def run(seconds, sync=False, servo=False, target_fraction=0.5):
    extra_a, extra_b = {}, {}
    if sync:
        from libcamera import controls
        extra_a["SyncMode"] = controls.rpi.SyncModeEnum.Server
        extra_b["SyncMode"] = controls.rpi.SyncModeEnum.Client
    cam_a, cam_b = open_camera(0, extra_a), open_camera(1, extra_b)
    a_rec = Recorder(cam_a)
    state = {"count": 0, "period_ns": None}
    log = []  # (t_seconds, phase_us, error_us, duration_us)
    started = {"t": None}

    def steer(stamp):
        # Called for every B frame: measure its phase against A and nudge B's frame duration.
        state["count"] += 1
        a = a_rec.stamps
        if len(a) < 60 or state["count"] % 2:
            return
        if state["period_ns"] is None:
            state["period_ns"] = (a[-1] - a[-50]) / 49.0
        period_ns = state["period_ns"]
        i = bisect.bisect_right(a, stamp) - 1
        if i < 0:
            return
        phase = ((stamp - a[i]) % period_ns) / 1000.0
        period_us = period_ns / 1000.0
        error = ((target_fraction * period_us - phase + period_us / 2) % period_us) - period_us / 2
        adjust = max(-200.0, min(200.0, 0.1 * error))
        duration = int(round(period_us + adjust))
        cam_b.set_controls({"FrameDurationLimits": (duration, duration)})
        log.append((time.monotonic() - started["t"], phase, error, duration))

    b_rec = Recorder(cam_b, steer if servo else None)
    try:
        for camera in (cam_b, cam_a):
            camera.start()
        started["t"] = time.monotonic()
        a_rec.start()
        b_rec.start()
        time.sleep(seconds)
    finally:
        a_rec.stop_event.set()
        b_rec.stop_event.set()
        time.sleep(0.2)
        for camera in (cam_b, cam_a):
            try:
                camera.stop()
                camera.close()
            except Exception:
                pass
    return a_rec, b_rec, log


def run_lock(hold_seconds, target_fraction=0.5, tolerance_fraction=0.08, max_attempts=25):
    """E3: no sync and no servo. Restart camera B alone until its phase to A lands on the target, then hold."""
    cam_a, cam_b = open_camera(0), open_camera(1)
    a_rec = Recorder(cam_a)
    b_stamps = []
    b_lock = threading.Lock()
    stop = threading.Event()
    errors = []

    def drain_b():
        try:
            while not stop.is_set():
                try:
                    request = cam_b.capture_request(wait=True)
                except Exception:
                    time.sleep(0.02)
                    continue
                try:
                    stamp = request.get_metadata().get("SensorTimestamp")
                finally:
                    request.release()
                if stamp:
                    with b_lock:
                        b_stamps.append(int(stamp))
        except Exception as error:
            errors.append(repr(error))

    attempts = []
    try:
        cam_a.start()
        a_rec.start()
        time.sleep(1.0)
        drainer = threading.Thread(target=drain_b, daemon=True)
        drainer.start()
        period_ns = None
        locked = False
        for attempt in range(1, max_attempts + 1):
            with b_lock:
                b_stamps.clear()
            cam_b.start()
            time.sleep(1.4)
            with b_lock:
                sample = list(b_stamps)
            a = list(a_rec.stamps)
            if len(sample) < 100 or len(a) < 100:
                attempts.append({"attempt": attempt, "note": "too few frames"})
                cam_b.stop()
                continue
            period_ns = (a[-1] - a[-100]) / 99.0
            period_us = period_ns / 1000
            series = phase_series(a, sample[len(sample) // 3:], period_ns)
            mean, sd, worst = circular_stats([p for _, p in series], period_us)
            fraction = mean / period_us
            error = abs(((fraction - target_fraction + 0.5) % 1.0) - 0.5)
            attempts.append({"attempt": attempt, "phaseFraction": round(fraction, 3), "sdUs": round(sd, 1)})
            if error <= tolerance_fraction:
                locked = True
                break
            cam_b.stop()
            time.sleep(0.2)
        hold = {}
        if locked:
            with b_lock:
                b_stamps.clear()
            time.sleep(hold_seconds)
            with b_lock:
                held = list(b_stamps)
            a = list(a_rec.stamps)
            series = phase_series(a, held, period_ns)
            period_us = period_ns / 1000
            third = max(1, len(series) // 3)
            for label, chunk in (("first", series[:third]), ("last", series[-third:])):
                mean, sd, worst = circular_stats([p for _, p in chunk], period_us)
                hold[label] = {"phaseMeanUs": round(mean, 1), "phaseFraction": round(mean / period_us, 3),
                               "sdUs": round(sd, 1), "maxDevUs": round(worst, 1)}
            span = (series[-1][0] - series[0][0]) / 1e9
            hold["driftUsPerSecond"] = round(((hold["last"]["phaseMeanUs"] - hold["first"]["phaseMeanUs"] + period_us / 2) % period_us - period_us / 2) / max(span, 1e-9), 2)
            gaps = intervals(held)
            hold["framesB"] = len(held)
            hold["missedFramesB"] = sum(1 for g in gaps if g > 1.5 * period_us)
            hold["frameIntervalMedianUs"] = round(statistics.median(gaps), 2)
    finally:
        stop.set()
        a_rec.stop_event.set()
        time.sleep(0.3)
        for camera in (cam_b, cam_a):
            try:
                camera.stop()
                camera.close()
            except Exception:
                pass
    return {"experiment": "E3 restart B until half a frame", "locked": locked, "attemptsUsed": len(attempts),
            "attempts": attempts, "hold": hold, "errors": errors + ([a_rec.error] if a_rec.error else [])}


def run_stress(cycles, dwell_frames=60):
    """E4: restart camera B alone many times while A keeps running. Time each cycle, count failures,
    and check A is undisturbed. A cycle is stop, start, then wait for enough frames to read the phase."""
    cam_a, cam_b = open_camera(0), open_camera(1)
    a_rec = Recorder(cam_a)
    b_stamps, b_lock, stop, errors = [], threading.Lock(), threading.Event(), []

    def drain_b():
        while not stop.is_set():
            try:
                request = cam_b.capture_request(wait=True)
            except Exception:
                time.sleep(0.01)
                continue
            try:
                stamp = request.get_metadata().get("SensorTimestamp")
            finally:
                request.release()
            if stamp:
                with b_lock:
                    b_stamps.append(int(stamp))

    rows, failures = [], []
    try:
        cam_a.start()
        a_rec.start()
        time.sleep(1.0)
        threading.Thread(target=drain_b, daemon=True).start()
        cam_b.start()
        time.sleep(0.5)
        for cycle in range(1, cycles + 1):
            started = time.monotonic()
            try:
                cam_b.stop()
                with b_lock:
                    b_stamps.clear()
                cam_b.start()
                first_frame = None
                while time.monotonic() - started < 4.0:
                    with b_lock:
                        count = len(b_stamps)
                    if count and first_frame is None:
                        first_frame = time.monotonic() - started
                    if count >= dwell_frames:
                        break
                    time.sleep(0.005)
                with b_lock:
                    sample = list(b_stamps)
                a = list(a_rec.stamps)
                if len(sample) < dwell_frames:
                    failures.append({"cycle": cycle, "note": f"only {len(sample)} frames"})
                    continue
                period_ns = (a[-1] - a[-100]) / 99.0
                period_us = period_ns / 1000
                series = phase_series(a, sample[10:], period_ns)
                mean, sd, _ = circular_stats([p for _, p in series], period_us)
                rows.append({"cycle": cycle, "seconds": round(time.monotonic() - started, 3),
                             "firstFrameSeconds": None if first_frame is None else round(first_frame, 3),
                             "phaseFraction": round(mean / period_us, 3), "sdUs": round(sd, 2)})
            except Exception as error:
                failures.append({"cycle": cycle, "error": repr(error)})
                time.sleep(0.5)
    finally:
        stop.set()
        a_rec.stop_event.set()
        time.sleep(0.3)
        for camera in (cam_b, cam_a):
            try:
                camera.stop()
                camera.close()
            except Exception:
                pass
    a = a_rec.stamps
    period_us = (a[-1] - a[0]) / (len(a) - 1) / 1000 if len(a) > 10 else 0
    gaps = intervals(a) if len(a) > 10 else []
    fractions = [r["phaseFraction"] for r in rows]
    in_window = lambda f, half: abs(((f - 0.5 + 0.5) % 1.0) - 0.5) <= half
    seconds = [r["seconds"] for r in rows]
    return {"experiment": "E4 restart stress", "cycles": cycles, "succeeded": len(rows), "failures": failures,
            "cycleSeconds": {"mean": round(statistics.fmean(seconds), 3), "max": max(seconds), "min": min(seconds)} if seconds else None,
            "firstFrameSeconds": {"mean": round(statistics.fmean([r["firstFrameSeconds"] for r in rows if r["firstFrameSeconds"]]), 3)} if rows else None,
            "phaseWithin0_10OfHalf": sum(1 for f in fractions if in_window(f, 0.10)),
            "phaseWithin0_15OfHalf": sum(1 for f in fractions if in_window(f, 0.15)),
            "phaseSdUsMax": max((r["sdUs"] for r in rows), default=None),
            "phaseFractionsSorted": sorted(fractions),
            "cameraA": {"frames": len(a), "missedFrames": sum(1 for g in gaps if g > 1.5 * period_us),
                        "intervalSdUs": round(statistics.pstdev(gaps), 2) if gaps else None},
            "errors": errors + ([a_rec.error] if a_rec.error else [])}


def summarize(name, a_rec, b_rec, log, seconds, servo):
    a, b = a_rec.stamps, b_rec.stamps
    result = {"experiment": name, "framesA": len(a), "framesB": len(b), "errors": [e for e in (a_rec.error, b_rec.error) if e]}
    if len(a) < 100 or len(b) < 100:
        return result
    period_ns = (a[-1] - a[0]) / (len(a) - 1)
    period_us = period_ns / 1000
    result["periodAus"] = round(period_us, 2)
    result["periodBus"] = round((b[-1] - b[0]) / (len(b) - 1) / 1000, 2)
    result["frameRateDifferencePpm"] = round((result["periodBus"] - result["periodAus"]) / result["periodAus"] * 1e6, 1)
    series = phase_series(a, b, period_ns)
    t0 = series[0][0]
    third = max(1, len(series) // 3)
    for label, chunk in (("first", series[:third]), ("last", series[-third:])):
        mean, sd, worst = circular_stats([p for _, p in chunk], period_us)
        result[f"{label}Third"] = {"phaseMeanUs": round(mean, 1), "phaseSdUs": round(sd, 1), "phaseMaxDevUs": round(worst, 1),
                                   "phaseFractionOfFrame": round(mean / period_us, 3)}
    # Drift between the first and last thirds of the run, in microseconds per second.
    span_s = (series[-1][0] - t0) / 1e9
    delta = ((result["lastThird"]["phaseMeanUs"] - result["firstThird"]["phaseMeanUs"] + period_us / 2) % period_us) - period_us / 2
    result["driftUsPerSecond"] = round(delta / max(span_s, 1e-9) * 1.0, 2)
    gaps_a, gaps_b = intervals(a), intervals(b)
    result["frameIntervalSdUs"] = {"A": round(statistics.pstdev(gaps_a), 2), "B": round(statistics.pstdev(gaps_b), 2)}
    result["missedFrames"] = {"A": sum(1 for g in gaps_a if g > 1.5 * period_us), "B": sum(1 for g in gaps_b if g > 1.5 * period_us)}
    if servo and log:
        target = 0.5 * period_us
        converged = next((t for t, phase, error, _ in log if abs(error) < 100), None)
        tail = [phase for t, phase, _, _ in log if t > seconds * 0.6]
        if tail:
            mean, sd, worst = circular_stats(tail, period_us)
            result["servo"] = {"targetUs": round(target, 1), "firstWithin100UsAtSeconds": None if converged is None else round(converged, 2),
                               "finalPhaseMeanUs": round(mean, 1), "finalSdUs": round(sd, 1), "finalMaxDevUs": round(worst, 1),
                               "finalErrorUs": round(((target - mean + period_us / 2) % period_us) - period_us / 2, 1),
                               "durationRangeUs": [min(d for *_, d in log), max(d for *_, d in log)]}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--only", choices=["E0", "E1", "E2", "E3", "E4"])
    parser.add_argument("--cycles", type=int, default=60, help="Restart cycles in E4")
    parser.add_argument("--hold", type=float, default=60, help="Seconds to hold in E3 after locking")
    parser.add_argument("--output", default="/tmp/stagger-phase.json")
    args = parser.parse_args()
    report = []
    if args.only in ("E3", "E4"):
        summary = run_lock(args.hold) if args.only == "E3" else run_stress(args.cycles)
        print(json.dumps(summary, indent=2), flush=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump([summary], handle, indent=2)
        return
    for name, sync, servo in (("E0 libcamera sync", True, False), ("E1 free-running", False, False), ("E2 free-running with servo to half a frame", False, True)):
        if args.only and not name.startswith(args.only):
            continue
        a_rec, b_rec, log = run(args.seconds, sync=sync, servo=servo)
        summary = summarize(name, a_rec, b_rec, log, args.seconds, servo)
        report.append(summary)
        print(json.dumps(summary, indent=2), flush=True)
        time.sleep(1.0)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)


if __name__ == "__main__":
    main()
