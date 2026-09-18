# LM1 setup validation v1.0.0

15 September 2026. Pi service 0.23.4; diagnostic audit tool 1.0.0.

## What the saved footage establishes

The latest capture, `capture-1789478965522399703`, contains 325 sensor-timestamped frames over 1.341 seconds. The measured rate is 241.57 fps, with a maximum interval of 4.144 ms and no gaps suggesting dropped frames. Image tracking follows eight outgoing frames, 177–184.

The Pi replay detects the floor tag and estimates the camera height above the tag plane at 215.2 mm and downward pitch at 13.04 degrees. The user measured the lens centre at 215 mm above the ground and reports a 2 mm raised surface. These measurements broadly agree; they do not by themselves prove the entire lens and ground calibration accurate. The print ruler checked correctly; keep the printed black square at 100 mm.

The strict ball-outline path accepts no frames. The partial-outline path considers five motion matches with sufficient tracking score, finds one candidate at frame 178, and rejects it because its calculated centre is 28.7 mm below the tag plane. Frames 182–184 are visible in the image track but do not pass the fallback's tracking-score threshold. The failure is therefore not a shortage of captured images.

The same patch inside the resting ball varies from 160.6 to 196.7 on the 0–255 brightness scale across the first 100 frames (maximum/minimum 1.225). An earlier capture varies by 1.287. Exposure is fixed at 143 microseconds and gain is 4.0. This variation is consistent with unsteady illumination. The difference-mask images show how the shaded ball edge disappears and the club/ball regions merge.

An experimental edge fit finds additional outline pixels but its frame-to-frame depth is unstable. It is not enabled in live measurements. More reported numbers would not establish more accurate measurements.

## Physical observation limit

The latest framing has approximately 0.222 m of ground-level travel to the right from the hitting position before the ball approaches the edge. This estimate assumes ground-level left-to-right travel and the current apparent radius; flight direction, lens errors and club occlusion reduce its usefulness.

At 50 m/s and 241.57 fps, the ball travels 0.207 m between frames. Three outgoing samples require at least two frame intervals, or approximately 0.414 m at that speed, plus margin for exposure phase and club overlap. Increasing post-trigger retention cannot recover observations outside the camera view. This framing is suitable for investigating slow shots; it cannot reliably provide three full-ball observations of a 50 m/s shot.

## Next controlled tests

1. Keep the camera, tag and focus fixed for the next test. Put the ball in the same hitting position and gently roll it left-to-right without a club next to it. Confirm the monitor is armed first. This isolates ball-outline extraction from club overlap. Do not infer airborne launch or spin from a ground-only model.
2. Repeat that roll with steadier, more even illumination on both the top and lower ball edge. Keep exposure and gain fixed so the comparison is meaningful. Compare the stationary brightness variation, accepted outline count, consecutive run length and ground/depth rejections in the saved diagnostics.
3. Fit the 28-degree bracket and inspect the framing. Keep the full ball inside the frame, with clear space below and along its outgoing path. Reset the empty-scene background and refresh ground/target-line calibration. Lens calibration needs repeating if focus or sensor mode changes; rotating the whole camera alone does not change its intrinsic lens parameters.
4. Validate a stationary ball and several slow rolls at left, centre and right positions. A resting ball centre should be about 21.3 mm above its supporting surface (about 19.3 mm above a tag plane raised 2 mm relative to that surface). Consistent position-dependent height errors indicate calibration/outline bias before any velocity calculation.
5. After clean rolls produce a stable sequence, repeat slow club strikes. Seek at least six to eight usable outgoing observations as an engineering test target; the software's three-frame minimum is only a minimum fit condition. Compare against an independent speed reference or a separately timed measured path before calling the speed accurate.
6. For faster shots, measure the required visible travel using `speed * frame intervals / actual fps`. Increase field coverage and/or actual sensor rate while keeping the ball large enough for outline measurement. Additional camera viewpoints can help club overlap and depth, but require synchronization and calibration work.

Core goal: dependable ball speed and launch/start direction first. Club speed and face strike require a calibrated club reference; reliable spin requires resolved surface features. Neither is solved by the current outline diagnostics.

## Files and repeatability

- `latest/audit-on-pi-v1.0.0.json`: replay on the Pi's OpenCV 4.10.0 runtime.
- `latest/audit-v1.0.0.json`: local OpenCV 5.0.0 replay. Small tag-pose differences across versions are recorded explicitly.
- `latest/outline-audit-v1.0.0.jpg`: camera frames beside the actual difference-mask algorithm output.
- `previous/audit-v1.0.0.json`: preceding capture comparison.
- `scripts/audit-capture.py`: repeatable read-only replay with explicitly supplied lens calibration.

Future service 0.23.4 captures save calibration matrices, tag size, inferred camera height/pitch, strict-outline counts and per-frame partial-outline rejection reasons in `analysis.json`. Detailed diagnostics stay off BLE; the shorter failure explanation reaches the app.
