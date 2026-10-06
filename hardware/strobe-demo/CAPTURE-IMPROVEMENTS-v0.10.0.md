# Capture findings — 0.10.0 / bridge 0.5.0

## What limits the current measurements

At the last estimated club-feature speed of 6.294 m/s, 120 fps spaces
observations about 52 mm apart. A 250 us flash allows about 1.57 mm of motion.
Only the time that the head remains visible near the ball provides useful
pre-impact positions. Extending a recording does not change this spacing.

The latest raw shot has useful intensity detail: sampled moving-ball cores
clip by 0–0.573%. Do not reduce flash energy merely because the display looks
white. A shorter pulse trades photon count for less blur and needs a real
moving-feature comparison.

Live trials:

| Requested rate | Primary delivered | Secondary delivered | Decision |
|---|---:|---:|---|
| 200 Hz, 150 us pulse | 100 fps | about 200 fps | Reject: alternate primary frames missing |
| 160 Hz, 187 us pulse | 80 fps | about 160 fps | Reject: alternate primary frames missing |
| 120 Hz, 250 us pulse | 120 fps | about 120 fps | Retain |

The faster trials kept LED duty at or below 3%. The primary trigger limit
requires a separate sensor/driver investigation; readout overhead alone is not
yet a proven explanation. No wiring, firmware or calibration change was made.

## Changes retained

- 350 ms of pre-departure data and 250 ms afterward; manual check saved 73
  raw frames from each camera, versus 46 in the previous shot.
- Up to 12 outgoing ball positions retained for replay, previously five.
- Calibration copied into each capture and validated before stereo replay.
- Recorded pulse width/delay used for exposure matching.
- Frame timing, inferred flash coverage and clipping saved in raw-quality.json;
  quality failures also accompany the app analysis warnings.
- Missing-ball recordings yield unavailable results instead of crashing.

Bench capture `capture-1790901129626628779`: primary 120.0048 fps, secondary
119.9472 fps, 42 pre-departure frames each, zero timing gaps, 72/73 inferred
shared-flash pairs. It was a manual scene check, not a golf measurement test.
Calibration replay used the capture snapshot. No ball or club metrics were
invented. Forty Python tests and the app payload/display regression passed.

## Next priorities using this hardware

1. Compare two new chips with saved raw head patches. Prefer the same textured
   feature across three or more positions; keep two-position results explicitly
   provisional. A changing reflective blob centroid is not a stable head point.
2. Investigate stereo calibration bias: recent ball rays miss by about 9–12 mm.
   More samples do not remove this bias. Club path and left/right direction
   need stronger geometric validation before they are trustworthy.
3. Benchmark shorter exposures and flash delay separately if pursuing higher
   trigger rates. Require both actual frame delivery and raw illumination tests
   before using a faster profile for shots.
4. Attempt spin only when multiple sharply resolved views show repeatable ball
   markings or dimple texture. Current inferred/model spin is not measured spin.

PiTrac's relevant principle is coordinated illumination, exposure timing and
calibrated views—not simply requesting a higher frame rate. Its camera approach
is described in [the PiTrac camera documentation](https://docs.pitrac.org/hardware/cameras/).
