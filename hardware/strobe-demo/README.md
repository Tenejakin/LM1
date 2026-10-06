# LM1 Strobe Lab — 0.10.0

Standalone unchanged-wiring prototype for the dual OV9281 cameras and existing
ESP32-S3 IR ring controller. It temporarily replaces camera ownership by the
normal Pi service. No app, BLE protocol, calibration or ESP32 firmware update
is required. The browser page is at `http://192.168.0.140:3113` on the local network.

## Capture improvement (0.10.0)

The verified profile remains 120 captures/s and one 250 us flash per trigger.
Live trials at 200 and 160 triggers/s delivered only 100 and 80 primary frames/s;
those rates are therefore disabled. The underlying sensor/driver trigger limit
has not yet been isolated. Increasing the requested rate alone loses data.

The rolling capture now retains 350 ms before departure and 250 ms afterward
(42 pre-departure frames instead of 24). A manual scene check saved 73 frames per
camera, compared with 46 in the previous shot: about 59% more saved frames,
not 59% more motion samples per second. Both cameras delivered approximately
120 fps, with no timing gaps and 72/73 inferred shared-flash pairs.

Each new raw capture includes a copy of its lens and stereo calibration. Replay
uses that snapshot so later calibration changes cannot silently change old
geometry. Ball tracking retains up to 12 outgoing positions instead of five.
Empty scenes return unavailable measurements instead of failing the review.

Bridge 0.5.0 writes `raw-quality.json` next to the app replay: actual frame rate,
pre-departure frame count, timing gaps, inferred complete-flash coverage and raw
ball-core clipping. Quality warnings accompany the app analysis. The raw values
remain 10-bit data stored in 16-bit PNGs; a white preview is not proof of sensor
saturation. The last moving-ball shot had at most 0.573% sampled core clipping.

Timing correspondence is inferred from camera exposure metadata and the ESP
programmed delay; electrical STROBE feedback has not validated the flash phase.
Keep the room dark for this single-flash experiment. Longer buffers preserve
more approach/follow-through evidence but cannot extend the cameras' field of
view. Next validation: a gentle and faster chip, comparing actual visible head
positions, template consistency, stereo ray mismatch and timing coverage.

## App bridge (0.5.0)

`app_bridge.py` runs the existing LM1 Bluetooth protocol alongside the demo,
without opening either camera or the ESP32 serial port. It registers recent
0.7.1/0.8.0 captures and newly completed shots, and persists app-compatible
analysis and replay frames separately under `/var/lib/pinpoint/strobe-app-captures`.
Reconnect the app to LM1 PRO; newly completed captures become live app shots.
Recent historical captures are retained on the Pi for explicit recovery; the
app does not automatically import device history on connection. Select the club
in the app before new shots; imported historical chips default to lob wedge.

Camera 1 now runs at 120 fps with an 8 ms shutter, while camera 0 keeps its
1.5 ms shutter and one 250 us flash per frame. The longer secondary shutter
catches the same flash. Exposures are paired only when metadata shows that
the complete flash lies within both shutters; they are not paired by nearest
sensor timestamp. This requires a dark room so the flash dominates motion.

The bridge uses the existing fixed stereo calibration (checked against both
lenses, resolution and camera order) and the user-confirmed level/image-right
target assumption. Paired ball rays yield provisional 3D speed, launch and
left/right direction. A consistent pre-departure head/hosel stereo track yields
provisional club speed, attack angle and club path; smash divides the speeds.
These are estimates requiring reference validation. Failed tracks remain
unavailable. Without paired ball rays the image-plane fallback still uses an
explicitly assumed zero direction for the existing app flight model. Spin and
strike position remain unavailable; modeled spin and carry are not measurements.
Original raw captures are retained.

When only two consistent same-feature club positions can be triangulated, the
bridge reports low-confidence interval speed, attack and path. It does not use
two points to replace a longer club track that failed physical checks. Two
positions cannot independently validate feature identity or swing curvature.

Version 0.3.0 also forwards a usable two-point side-view club pair as a
low-confidence estimate (0.15) when stereo club tracking fails. Feature identity,
rotation and depth remain unverified; the reason is included in every metric.
It does not derive a left/right club path from that side-view angle. Stereo ball
rays missing by 6–12 mm are admitted only as low-confidence estimates (0.2),
with calibration bias and possible direction-sign error stated explicitly.
Ball-circle matching weighs radius agreement so a clipped bright-core contour
does not displace a better full-ball circle simply to reduce the ray gap.
Recent 0.9.1/0.10.0 shot analyses are upgraded under their existing capture IDs and
original timestamps, preserving club selection and avoiding duplicate shots.
Revised recent shots wait for the app's connection/status handshake before
delivery, so restarting the bridge does not send their initial fragments before
the app subscribes.

Version 0.4.0 searches for a broad head region near the shaft's projected ground
intersection, then matches a textured patch across consecutive pre-departure
frames. Correlation below 0.7, stationary motion, an image-border component,
or a ball-clipped head is rejected. A matched patch can provide provisional
image-plane club-feature speed and attack even when the visible head's area
changes with orientation; smash is the ratio of estimated speeds. Patch
correlation and the remaining depth/identity assumptions accompany the metrics.
Run this bridge instead of `pinpoint.service` while the demo owns the hardware.
Camera calibration commands are blocked while the demo runs to prevent another
camera owner. The bridge service is installed for this test and is not enabled
at boot. The demo must be running for live capture.

## Club visibility trial (0.7.1)

Version 0.8.0 also writes `review.json` for each new club-mode capture, with ball
trajectory, two-point/multi-position launch fits, velocity components, observed
displacement, departure bracket, and provisional club pair calculations. These
use the user's level-camera assumption. Two club candidates are sufficient for
provisional arithmetic but their identity remains unverified. Shaft orientation
is not face angle. `full_shot_review.py` exports saved shots to HTML and JSON.

Run `demo.py --club-mode --sync-camera0`. Camera 0 receives 120 triggers/s,
one 250 us flash 1 ms after each trigger, a requested 1.5 ms exposure, and gain 4.
The sensor uses its 242 fps limit to leave readout time between triggers.
Measured delivery is 8.333 ms per frame with 1491 us actual exposure. Camera 1
continues independently; stereo estimates require both exposures to contain
the same full flash as described above.

Saved summaries include `clubAnalysis`, and the page displays the latest club
result or rejection reason. A consistent pre-departure head-centroid path can
produce an experimental image-plane speed assuming the head is at ball depth.
This is not calibrated clubhead-centre speed. Attack angle remains unavailable
until the same physical club feature, flash correspondence and ground-relative
3D path are verified. Shaft endpoints and ball launch direction are not attack angle.

`--copies --sync-camera0` restores the three-copy ball experiment: 50 Hz,
8 ms exposure, 100 us flashes with 2.5/4 ms start spacings. Replayed multi-flash
club reflections do not become single-flash club measurements.

## Original free-running capture profile (0.3.2)

- 640 × 400, raw 10-bit words retained losslessly as 16-bit PNGs (count × 64).
- Both sensors free-run at 242 fps, 250 µs requested exposure, gain 4.
- ESP32: 250 Hz bursts, sixteen 20 µs flashes with 250 µs start intervals.
  The 4000 µs repeating period has the same spacing across its boundary, at 8% duty.
- IR supplies pulsed illumination inside short camera exposures. Positions are
  timed by the sensor, not by resolving individual flash copies. The continuous
  ambient contribution is still present; optical exposure is not claimed to be 20 µs.
- Trigger output stays off. No electrical camera synchronization is claimed.
- Each stream has its own sensor timestamps, actual exposure and gain metadata.
- 24 pre-trigger frames and approximately 180 ms after departure are retained.
- Before arming, both cameras locate the resting ball near the usual placement;
  green circles follow its actual position, which becomes the track origin.
- Replace the ball after each capture; the demo arms after a stationary interval
  with contrast and a clear surrounding annulus. Departure compares normalized
  ball-patch shape, so changes in pulse brightness cannot alone trigger it.
- Every departure/occlusion is a diagnostic capture, including rejected attempts.
- Positive, negative and absolute background-difference sweeps look for round
  ball silhouettes against the mat, floor, and their boundary, and require at least three
  consecutive sensor-timed positions, consistent size, a path originating at
  the resting ball, low fit residual and an estimated blur bound below 6 mm.
  Prefer the earliest valid interval. Conflicting positions over overlapping
  frames invalidate the estimate; different later interval speeds alone do not.
  Rejected fits retain their blur, origin and residual reasons. The old cyclic pulse fitter
  remains available for experiments with separated flashes; it is not used by
  this capture profile.
- Accepted numbers are **image-plane estimates** using reference ball diameter.
  Camera pitch, perspective, depth and stereo synchronization are not resolved.
  Spin, 3D direction and carry are unavailable.

`summary.json` retains the pulse pattern, per-view timestamps, candidate fits,
rejections and reference geometry. `contact.jpg` shows frames around departure.
The underlying raw frames and reference images are retained for offline iteration.

## Run on the Pi

Use the existing `/opt/pinpoint/.venv/bin/python`; no package installation needed.

```sh
sudo systemctl stop pinpoint
/opt/pinpoint/.venv/bin/python /home/lm1/strobe-demo-v0.3.2/demo.py
```

For the test session this runs under a temporary `lm1-strobe-demo` systemd unit.
Version 0.3.2 logs shutdown reasons and runs with `Restart=always` and
`RestartSec=3`, so unexpected process exits recover automatically.
Stop it before restarting `pinpoint`; they must never own the devices together.

```sh
sudo systemctl stop lm1-strobe-demo
sudo systemctl start pinpoint
```

Normal exit returns the ring to steady light. The existing ESP32 watchdog also
returns it to steady light if the host heartbeat stops. Captures are stored in
`/home/lm1/strobe-demo-v0.3.2/captures/`. There is no automatic capture deletion.
First prototype validation is against synthetic timing plus live static hardware;
moving-ball performance must be established from the user's wedge shots.

## Bench observations — 2026-10-01

At gain 4, stationary-ball raw data clips during long exposures. At gain 1,
4000 µs requested exposure, 60 µs flashes add about 71 raw counts in each view
in the sampled static setup. Near-full 8000 µs exposure with 100 µs flashes adds
about 100 raw counts averaged across the stationary ball. The stationary ball
partly clips, so these numbers establish visible flash contribution, not optical
pulse duration or moving-ball accuracy. Ambient light remains substantial.
`bench.py` contains the initial gain-4 diagnostic sweep; the Pi also retains the
gain-1 follow-up and its report in `/home/lm1/strobe-demo-v0.1.0/bench/`.

Version 0.1.1 adds ball-to-surrounding contrast to the arming check, so the empty
mat cannot automatically arm after a shot, and maps previews across the full
raw sensor range. Version 0.1.0 completed a live static capture in both views
without inventing a ball-speed result; both streams sustained approximately
120 fps, with frame intervals near 8.338 ms.

## First shot review and 0.2.0 changes

Version 0.1.1 retained three actual wedge shots and one placing-hand trigger.
All shot windows cover departure in both cameras, but the moving ball is an
elongated overlapping image rather than three resolved copies. No numerical
result was emitted. The first pattern cannot time those attempts unambiguously.
Their raw frames, timing and contrast reviews remain in the 0.1.1 directory and
were copied into `output/strobe-demo-v0.1.1/captures/` in the workspace.

Version 0.2.0 reduces exposure from 8000 to 500 µs and doubles camera sampling
rate, testing dense IR illumination and silhouette tracking for these shots.
It does not reinterpret the old long-exposure data as short-exposure data.
Ten focused tests on the Pi verify pulse timing rejection, frame-timed speed,
wrong-origin rejection, brightness-invariant departure and hands-clear arming.
Further moving-ball validation requires another shot batch.

## Second shot review and 0.3.0 changes

Four 0.2.0 shots were retained. The third produced an upper-view image-plane
estimate of 10.08 m/s from three points (0.65 px fit residual). The first and
fourth have coherent detections but fail the unchanged 6 mm blur gate at the
recorded 497 µs exposure. The ball becomes dark against the floor, where the
original positive-only detector loses it.

Version 0.3.0 adds bright/dark/boundary detection and halves the requested shutter
to 250 µs, increasing gain to 4 to maintain approximately the same ambient signal.
The ring pattern and 8% electrical duty are unchanged. Replay of the original
497 µs data preserves the third shot's upper estimate, recovers a later lower
view track on shot two and another lower track on shot three, and still rejects
the blur-limited shots. Those later image-plane speeds are not calibrated launch
speeds and should not be averaged with earlier intervals. Raw metadata is never
rewritten to simulate the new shutter. Twelve focused tests pass on the Pi.
Replay results and annotated frames are in `output/strobe-demo-v0.3.0/replay-v0.2.0/`.
The new live exposure still requires user-shot validation.

Version 0.3.1 locates the resting ball in both views before learning the reference,
fixing arming when placement differs from the original fixed circle. Thirteen
focused tests pass on the Pi, including a ball displaced from that anchor.
