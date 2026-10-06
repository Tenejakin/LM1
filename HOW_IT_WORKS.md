# How LM1 works (plain-language overview)

Written 2026-10-06 from the code on branch `strobin-effect`. This is a map, not a spec.
For the exact numbers see `raspberry_pi/README.md`, `LAUNCH_MEASUREMENTS.md` and `LLM_HANDOFF.md`
(the older docs lag behind the code in places).

## The big picture

```text
 2 cameras (OV9281, global shutter)      ESP32-S3 + IR ring
        │  ~242 fps, 640x400                │  steady / strobe / off
        ▼                                   ▲
   Raspberry Pi 5  ───── USB serial ────────┘
        │  watches for a ball, keeps the last ~1.4 s of frames,
        │  measures the shot when the ball disappears
        ▼  Bluetooth LE (no Wi-Fi needed)
   LM1 phone app  ───────►  OpenGolfSim / webhook
```

Three parts, all in this repo:

| Part | Where | Job |
| --- | --- | --- |
| Pi service | `raspberry_pi/` | cameras, shot detection, all the computer vision |
| Phone app | `src/` | arm/disarm, club choice, calibration, show shots, send to simulator |
| Hardware | `hardware/` | enclosure, camera brackets, IR ring, strobe sketches for the ESP32 |

## Life of one shot

1. **Learn the empty mat.** On start (or after a reset) the Pi averages the first few frames
   into a *background* picture of the hitting area (`BallPresenceDetector` in `ball_detector.py`).
   Keep the area clear while this happens.
2. **Wait for a ball.** Every few frames the current picture is compared with that background.
   A compact, round, *brighter-than-background* blob of the right size, sitting still for a few
   samples, becomes "ball present" and the monitor arms. The readiness checks (`readiness.py`)
   then tell you if the ball is the right size on screen (40-56 px across is the sweet spot) and in the
   right place.
3. **Record continuously.** While armed, every frame from both cameras goes into a rolling
   RAM buffer (`RollingFrameBuffer`). Nothing is saved yet; old frames fall off the end.
4. **Notice the hit.** When the ball disappears the Pi marks a *suspected departure* time at once,
   then waits a short debounce to be sure (a club covering the ball or a shadow must not count).
   Because the buffer already holds the moments before and after, nothing is missed.
5. **Measure** (`analyze_departure` → `measure_launch` in `launch_measurements.py`), from the buffered frames:
   - **Ball track.** Take a picture of the resting ball, find it in every frame by template matching
     (sub-pixel), keep the outgoing run of positions.
   - **3D.** With both cameras calibrated (lens + stereo pair + the ground AprilTag or the level-rig
     constants) each frame's ball position is triangulated into millimetres. Three paired frames are
     enough for a measured-grade fit.
   - **Fit** a straight/gravity trajectory through the points: ball speed, launch angle, direction.
   - **Club.** Subtract a median "before" picture from each frame; what is left is the moving club.
     The head and hosel give club speed, attack angle, path, and where on the face the ball was hit.
   - **Spin.** Optical flow on the ball's surface pattern between frames (needs visible marks),
     otherwise a club-based estimate is used and labelled as such.
   - **Carry.** A drag/lift flight model from speed, angle and spin (`flight_model.py`).
6. **Grade it.** `grade_metrics` runs gates (timing, exposure, geometry, fit residual...). A value that
   passes all of them is "measured"; the rest are "estimated", with a confidence. Rejected shots
   get a plain-language reason (`rejection_hints.py`).
7. **Send** the result over BLE to the app, then save the frames to
   `/var/lib/pinpoint/rolling-captures/capture-*/` (newest 100 kept) so you can review/replay them.

## Cameras

- Two OV9281 global-shutter cameras, **640x400 at ~242 fps** (the ball is ~52 px across there;
  1280x800 only runs ~115 fps and was not worth it).
- **Staggered mode** (on): the second camera is offset by half a frame so the pair gives ~480
  views per second. `camera_source.py` owns this and re-locks itself while the mat is empty.
- A frame is only used for measurement if exposure is **250 µs or shorter**, and the blur estimate
  (ball speed x exposure) stays under 4 mm.

## Light (indoors, dark, outdoors)

`light_controller.py` talks to the ESP32, which drives the IR ring. The app's **Light** selector:

| Mode | Ring | Use |
| --- | --- | --- |
| Daylight | off | sun or bright room: short exposure, no help needed |
| Flat | steady on | normal indoor shooting |
| Strobe | pulsed bursts | dark-room experiment: several ball copies in one frame (measurement of those is not done yet) |
| Auto | picks from the exposure sweep | tap it after moving the unit |

Each mode remembers its own exposure and gain. **Auto-set** sweeps exposure with the ring off first;
if <= 100 µs is enough, it is Daylight, otherwise Flat. It also caps exposure by club
(driver ~58 µs, 7-iron ~85 µs, PW ~100 µs) so the ball does not blur.

## Where "subtract the background" already happens

Reference-frame subtraction is already the backbone of the detector. Three separate places:

| Where | Reference | Used for |
| --- | --- | --- |
| `BallPresenceDetector.update` | running average of the empty mat | deciding a ball is placed / gone. Brighter-only, brightness-normalised against lamp flicker |
| `ball_background` + `motion_mask` | median of the pre-hit frames of that shot | finding the flying ball's outline and the club silhouette |
| `club_stereo.head_pixel` | same median | club head centre, **both** brighter and darker (`absdiff`) |

The weak spot for sunlight is that `motion_mask` (`club_vision.py`) only sees pixels *brighter*
than the background (`cv2.subtract` clips at zero). Over bright grass a dark club head
produces no difference at all. That is why a bright patch on the club (foil or white tape) helps.

## The app

React Native / Expo app (`src/`). It connects over BLE, sends commands (arm, mode, light, club,
calibration), receives `status`, `capture` and `shot` events, shows results with each metric's
source and confidence (measured / estimated), keeps history and sessions, and forwards shots to
OpenGolfSim (`src/services/opengolfsim.ts`). The Pi never needs a network for this.

## Calibration (set once, redo if the rig moves)

1. **Lens** per camera (checkerboard images) - removes distortion.
2. **Stereo pair** - where camera 2 is relative to camera 1.
3. **Ground** - a printed AprilTag on the mat (or the level-rig constants in `rig.json`) defines the
   floor and the target line. The tag can be removed afterwards.

## Handy facts

- Ball size on screen predicts success: 40-56 px measured 44 of 53 shots, outside it most failed.
- Pi service name `pinpoint`, config `/etc/default/pinpoint`, code `/opt/pinpoint`, data `/var/lib/pinpoint`.
- The old "tag on the club" path still exists; tag-free club tracking is the default.
- Everything is still an unvalidated hobby measurement: compare with a reference monitor before trusting numbers.

## Key files

| File | One line |
| --- | --- |
| `raspberry_pi/ball_detector.py` | presence detector, rolling buffer, the main camera loop (`BallMonitor.run`) |
| `raspberry_pi/launch_measurements.py` | ball/club/spin/roll measurement and grading |
| `raspberry_pi/club_vision.py`, `club_stereo.py` | club silhouette and head tracking (mono and stereo) |
| `raspberry_pi/stereo_check.py` | two-camera pairing and consistency checks |
| `raspberry_pi/camera_source.py` | cameras, stagger, raw 10-bit option |
| `raspberry_pi/exposure_calibration.py` | Auto-set exposure/gain |
| `raspberry_pi/light_controller.py` | ESP32 ring control |
| `raspberry_pi/readiness.py` | "is the ball in the right place" checks |
| `raspberry_pi/pinpoint_protocol.py`, `pinpoint_ble.py` | BLE commands and state machine |
| `hardware/strobe-test/` | ESP32 sketches (`strobe_master` is the real one) |
