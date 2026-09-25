# Fixed-pair calibration — workflow version 1.0.0

Available in app 3.17.0 / Pi 0.37.0 / protocol 2.24.0.

## App workflow

1. Keep both cameras rigidly attached; lock lens focus. Calibrate each lens at the
   actual capture resolution first. Stereo calibration does not alter lens files.
2. Open **Calibration → Calibrate both cameras as a fixed pair**.
3. Enter checkerboard INNER-corner columns and rows and measured square size.
   Defaults match the existing 5×5 inner-corner, 25 mm board. Mount it flat on a
   rigid backing. A square size error creates a scale error even with good fit.
4. Start a new set. Existing sessions and active calibration are retained.
5. Hold the entire board still and clearly visible in both previews. Capture at
   least 16 distinct pairs, ideally 20–28, distributed left/right, high/low and
   near/far, with forward/back and sideways tilts. Move only the board, never the
   cameras. The previews are live, not evidence that a capture succeeded.
6. Press **Capture synchronized pair** at each pose. Images come from the same
   dual-camera read, with actual sensor timestamps, not the phone previews.
   Both board detections must succeed; missing timestamps, more than 250 µs skew,
   near-edge corners and near-duplicate poses are rejected. Accepted PNG pairs,
   corners, timestamps, camera order and lens inputs stay on the Pi.
7. Press **Solve camera pair**. Every fourth accepted pair is held out. At least
   12 training and 4 validation views are required. Training must cover multiple
   positions and tilts. Intrinsics remain fixed during OpenCV stereoCalibrate.
   Symmetric board corner rotations are aligned by transform consistency across
   training views; validation ordering is compared against the frozen transform.
8. Review separation and errors. Initial engineering gates: training RMS ≤0.7 px,
   held-out prediction RMS ≤1.0 px, worst held-out view ≤2.0 px, separation
   10–1000 mm. These are quality gates, NOT a guarantee of millimetre accuracy.
   Failed candidates remain visible but cannot be activated. Capture more varied,
   sharp views, or start a new set if existing views are poor.
   The app also shows a 0–100 fit score. A score of 100 means training RMS ≤0.35 px,
   held-out RMS ≤0.50 px, and worst held-out view ≤1.00 px. It summarizes margin
   inside the validation limits; it is not a physical accuracy measurement.
9. **Use this calibration** explicitly activates a passed candidate. The previous
   active file is backed up. Existing lens, ground and shot-history files are not
   rewritten. Verify the reported separation against the physical mount.
10. Remove the board before closing the screen. Shot detection is paused while
    the screen is open, and its empty-scene model resets on exit. If the phone
    disconnects, the pause expires after 120 seconds without a refresh.
11. Capture/check the bottom-camera ground AprilTag after moving the rig. Future
    shots use the bottom ground pose plus the fixed pair transform for the top
    camera. Left-to-right camera-relative zero direction is unchanged. Validate
    known stationary ball positions/heights before trusting launch estimates.

## Storage and safety

Default root: `/var/lib/pinpoint/stereo` (`PINPOINT_STEREO_PATH` override).
`sessions/<uuid>/session.json` stores board, lens inputs, accepted paired corners
and timing; matching PNGs are adjacent. `candidate.json` is a staged result.
`current.json` points to the current resumable session. `active.json` is the
atomic active selection; previous selections are under `backups/`.

The fixed transform uses `X_secondary = R_pair X_primary + t_pair`. Therefore
`R_secondary_world = R_pair R_primary_world` and
`t_secondary_world = R_pair t_primary_world + t_pair`.

If no fixed calibration exists, legacy independent ground poses still work.
If an active calibration exists but lens parameters, image size or configured
camera indices differ, stereo fails explicitly; stale geometry is not used.
Changing physical focus/mount position cannot be detected reliably by a file
fingerprint: recalibrate after either changes. New capture manifests include the
active stereo snapshot for diagnosis. Old captures are not reprocessed.

## Offline script

Use the same solver on an existing paired session (OpenCV and NumPy required):

```sh
python stereo_calibration.py --session /path/to/session.json --output /path/to/candidate.json
```

The command writes a candidate only; it never activates it or captures from a
second competing camera handle. Use a new output path to preserve older reports.

BLE command: `stereoCalibration`, actions `status`, `start`, `capture`, `solve`,
`activate`, `end`. Start accepts `columns`, `rows`, `squareMm`; activate requires
the exact staged `candidateId`. Capture replies only after the camera callback
has saved or rejected the paired images. A compact status is returned for each
action. The app polls status every 30 seconds while idle to keep the pause alive.

Reference: [OpenCV stereo calibration](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html),
using `CALIB_FIX_INTRINSIC` and independent held-out cross-camera reprojection.
