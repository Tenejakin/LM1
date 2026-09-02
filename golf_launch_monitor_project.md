# Golf Launch Monitor Project

## Project Goal

Build a compact DIY camera-based golf launch monitor using:

- Raspberry Pi 5 1GB
- OV9281 global-shutter camera
- High-speed capture around 300 FPS
- Front-diagonal camera placement
- Strong continuous LED lighting
- Impact trigger
- Rolling RAM buffer
- Computer vision for ball and club tracking
- Optional phone app for heavy processing and UI

The first version should measure:

- Ball speed
- Club speed
- Smash factor
- Impact location on the clubface
- Launch angle estimate
- Start direction estimate

The system should prioritize repeatability, simple hardware, and visual verification of every measurement.

---

# 1. Core Architecture

The Raspberry Pi should act primarily as a high-speed capture device.

It should not try to perform all computer vision continuously while recording at high frame rate.

Pipeline:

```text
OV9281 camera
      |
      v
Raspberry Pi 5
      |
      +-- continuous RAW capture
      +-- accurate timestamps
      +-- rolling RAM buffer
      +-- impact trigger
      |
      v
Shot detected
      |
      v
Keep short frame burst around impact
      |
      v
Analyze locally or send to phone
      |
      v
Ball speed
Club speed
Smash factor
Impact location
Launch angle
Start direction
```

---

# 2. Hardware

## Required

- Raspberry Pi 5 1GB
- OV9281 global-shutter camera
- CSI cable compatible with Raspberry Pi 5
- Raspberry Pi 5 power supply
- Active cooling
- Continuous LED lighting
- Piezo sensor or microphone for impact triggering
- Protective polycarbonate window
- Enclosure

## Optional later

- Second OV9281 camera
- iPhone app
- iPhone LiDAR-assisted calibration
- Reflective clubhead markers
- IR illumination
- Doppler radar as secondary speed validation

---

# 3. Camera Placement

The launch monitor should sit in front of the golf ball and slightly offset from the target line.

Suggested starting geometry:

- 30 to 60 cm in front of the ball
- 20 to 40 cm sideways from target line
- 10 to 25 cm above the floor
- Approximately 30 to 45 degrees relative to target line
- Camera pointed back toward impact area

Top view:

```text
Golfer
   |
   |
   ● BALL  --------------------> TARGET
      \
       \
        \
      [CAMERA]
```

This position should provide useful visibility of:

- Clubhead approaching impact
- Clubface near impact
- Ball immediately after launch
- Horizontal start direction
- Strike position

The camera should not sit exactly on the target line.

---

# 4. Camera Configuration

Initial target mode:

```text
Resolution: 640 x 400
Pixel format: RAW8 / grayscale
Frame rate: approximately 300 FPS
Shutter: global shutter
Exposure: manual
Focus: fixed
```

Target exposure:

```text
1/5000 s to 1/10000 s
```

Use the shortest exposure that still produces a bright enough image.

The goal is not image quality.

The goal is:

- sharp ball edges
- sharp clubhead
- high contrast
- consistent exposure
- minimal motion blur

---

# 5. Field of View

Target around:

```text
1.0 to 1.5 metres horizontal coverage
```

around the impact area.

Example:

If 640 pixels represent 1.2 metres:

```text
1200 mm / 640 px = 1.875 mm per pixel
```

A golf ball is approximately 42.7 mm diameter:

```text
42.7 / 1.875 = ~23 pixels
```

That should be enough for reliable ball-center detection.

---

# 6. Frame Timing

At approximately 309 FPS:

```text
1 frame ~= 3.23 ms
```

A golf ball travelling at 60 m/s moves:

```text
60 x 0.00323 ~= 0.194 m
```

So it moves roughly 19 cm between frames.

This means the camera should capture a sufficiently wide area after impact.

---

# 7. Lighting

Strong lighting is essential.

Use:

- Continuous LEDs
- DC-powered lights
- No low-frequency PWM flicker
- Diffusion
- Multiple light angles if possible

Lighting should allow very short exposure times.

Suggested layout:

```text
LED --------\
             \
              ● BALL
             /
LED --------/
```

Color accuracy does not matter.

The OV9281 is monochrome, which is useful for this purpose.

---

# 8. Rolling Buffer

The camera continuously records into RAM.

Do not continuously write raw high-speed video to the SD card.

Suggested buffer:

```text
300 ms before impact
300 ms after impact
```

At approximately 309 FPS:

```text
~93 frames before
~93 frames after
~186 frames total
```

A 640 x 400 RAW8 frame:

```text
640 x 400 = 256,000 bytes
~250 KB
```

Approximately 186 frames:

```text
~47 MB
```

This is small enough for Raspberry Pi 5 1GB.

Even one full second of raw frames is roughly:

```text
~79 MB
```

---

# 9. Impact Trigger

Use a piezo sensor or microphone as a trigger.

The trigger does not need to identify the exact impact instant.

It only needs to tell the software:

```text
A shot probably happened.
```

The rolling buffer already contains the frames before impact.

Flow:

```text
Camera continuously buffering
        |
Impact sound detected
        |
Keep previous frames
        |
Capture additional frames
        |
Freeze shot buffer
```

---

# 10. Finding the True Impact Frame

Do not trust the sound sensor as the exact impact timestamp.

Use computer vision.

Before impact:

```text
ball stays stationary
```

After impact:

```text
ball suddenly moves
```

Example:

```text
Frame 125: stationary
Frame 126: stationary
Frame 127: stationary
Frame 128: ball moved
```

Impact occurred between frames 127 and 128.

This becomes the true visual impact timestamp.

---

# 11. Ball Detection

Start with classical OpenCV.

Possible methods:

- Background subtraction
- Motion detection
- Grayscale thresholding
- Blob detection
- Circle or ellipse detection
- Known starting ball region

Store for each frame:

```text
frame_id
timestamp
ball_x
ball_y
confidence
```

Example:

```text
127 | 312 | 219
128 | 401 | 205
129 | 492 | 190
130 | 587 | 175
```

---

# 12. Camera Calibration

Pixel coordinates must be transformed into physical coordinates.

Use:

- Checkerboard
- ArUco board
- AprilTag board

Place the calibration target through the hitting area.

Calibration should determine:

- Camera intrinsic parameters
- Lens distortion
- Camera orientation
- Pixel-to-world mapping
- Hitting plane
- Floor plane

Save calibration:

```text
calibration.json
```

The camera should remain fixed inside the launch monitor.

---

# 13. Ball Speed

Track the ball across several frames.

Do not calculate speed from only two frames.

Use:

```text
position + timestamp
```

for several points.

Then fit a trajectory.

Basic formula:

```text
velocity = distance / time
```

Use calibrated real-world distance.

Output:

```text
Ball Speed: 61.8 m/s
```

---

# 14. Club Speed

Track the clubhead over several frames before impact.

Example:

```text
Frame -5     CLUB
Frame -4        CLUB
Frame -3           CLUB
Frame -2              CLUB
Frame -1                 CLUB + BALL
```

Calculate calibrated clubhead movement.

Estimate the clubhead velocity at the impact timestamp.

Output:

```text
Club Speed: 42.4 m/s
```

---

# 15. Smash Factor

Formula:

```text
Smash Factor = Ball Speed / Club Speed
```

Example:

```text
61.8 / 42.4 = 1.46
```

---

# 16. Impact Location

This is expected to be the hardest V1 measurement.

The camera does not need to photograph the exact instant of ball compression.

Instead estimate contact using:

- Ball center
- Clubhead position
- Clubhead orientation
- True impact timestamp
- Known clubface geometry

Calculate where the ball intersects the clubface plane.

Output example:

```text
CLUB FACE

┌───────────────────┐
│                   │
│          X        │
│                   │
└───────────────────┘

7 mm toe
2 mm high
```

---

# 17. Club Markers

If club tracking is unreliable, add small visual markers.

Possible markers:

- White dots
- Reflective dots
- IR reflective markers

Example:

```text
        •
   ┌─────────┐
   │ CLUBHEAD│
   └─────────┘
       •
```

Markers can make clubhead:

- Position
- Rotation
- Orientation
- Face geometry

much easier to estimate.

---

# 18. Launch Angle

Track post-impact ball positions.

Example:

```text
                ●
             ●
          ●
       ●
    ●
```

Fit a line or initial trajectory.

Calculate angle relative to the calibrated floor.

Because V1 uses one camera, this is still a projected 3D estimate.

Target V1 accuracy:

```text
±2 to 3 degrees
```

---

# 19. Start Direction

Use the calibrated ball trajectory to estimate:

- Left
- Center
- Right
- Angle relative to target line

Example:

```text
Start Direction: 1.8 degrees right
```

With one camera this remains an estimate.

---

# 20. Raspberry Pi Software

Suggested project structure:

```text
launch-monitor/
│
├── capture/
│   ├── camera.cpp
│   ├── ring_buffer.cpp
│   └── timestamps.cpp
│
├── trigger/
│   ├── gpio.cpp
│   └── trigger_filter.cpp
│
├── vision/
│   ├── ball_detector.py
│   ├── club_detector.py
│   ├── impact_detector.py
│   └── trajectory.py
│
├── calibration/
│   ├── camera_calibration.py
│   └── calibration.json
│
├── calculation/
│   ├── ball_speed.py
│   ├── club_speed.py
│   ├── launch.py
│   └── strike.py
│
├── server/
│   └── api.py
│
├── debug/
│   └── replay.py
│
└── config/
    └── config.yaml
```

---

# 21. Programming Languages

Start with:

- Python
- Picamera2
- OpenCV

If Python cannot reliably sustain the required high-speed capture:

Move only the capture layer to:

- C++
- libcamera

Keep analysis in Python initially.

---

# 22. Operating System

Use:

```text
Raspberry Pi OS Lite 64-bit
```

No desktop environment required.

Launch monitor runs as a systemd service.

Example state machine:

```text
BOOT
  |
CAMERA INIT
  |
READY
  |
ARMED
  |
IMPACT DETECTED
  |
CAPTURE COMPLETE
  |
PROCESSING
  |
RESULT
  |
READY
```

---

# 23. Shot Storage

During development, save captured shots.

Suggested structure:

```text
shots/
└── 000001/
    ├── metadata.json
    ├── frame_000.raw
    ├── frame_001.raw
    ├── frame_002.raw
    ├── ...
    └── result.json
```

Metadata should include:

```text
FPS
Exposure
Gain
Frame timestamps
Impact frame
Calibration version
Device position
Software version
```

---

# 24. Replay System

Recorded shots must use the same analysis pipeline as live shots.

Workflow:

```text
Hit 100 balls
      |
Save all raw shots
      |
Develop algorithm on PC
      |
Replay all 100 shots
      |
Compare results
```

This avoids needing to physically hit balls every time software changes.

This should be treated as a major project requirement.

---

# 25. Debug Interface

Create a local browser interface.

Display:

```text
SHOT #153

Frame: 102 / 186

Ball:
X: 442
Y: 204
Confidence: 98%

Club:
X: 261
Y: 217
Confidence: 91%

Impact frame: 97

Ball Speed: 61.2 m/s
Club Speed: 41.9 m/s
Smash: 1.46
Launch: 14.2 deg
Direction: 1.8 deg R
```

Overlay detected objects directly on frames:

```text
ball circle
clubhead box
trajectory line
impact marker
```

Every incorrect measurement should be visually diagnosable.

---

# 26. Calibration Levels

## Device calibration

Done during assembly:

- Lens distortion
- Camera intrinsics
- Camera position relative to enclosure
- Camera angle

## Installation calibration

Done when the launch monitor is placed:

- Floor plane
- Ball origin
- Target line
- Device distance
- Device height

## Optional iPhone calibration

An iPhone with LiDAR can help measure:

- Floor
- Ball position
- Device position
- Height
- Distance
- Target line

LiDAR should assist setup only.

It should not be used to track the actual golf ball.

---

# 27. Phone Integration

Later architecture:

```text
OV9281
  |
Pi 5
  |
shot frame package
  |
Wi-Fi
  |
Phone
  |
Computer vision / ML
  |
Shot UI
```

The Pi should not stream continuous 300 FPS video.

Send only the short shot capture.

Phone can handle:

- Heavy OpenCV
- ML
- Shot history
- Charts
- Calibration
- Cloud storage
- User interface

This makes Pi 5 1GB practical.

---

# 28. Future Second Camera

The enclosure should have room for another OV9281.

Do not add it until V1 works.

A second synchronized camera would improve:

- True 3D trajectory
- Launch angle
- Start direction
- Club path
- Strike location
- Measurement redundancy

Suggested future architecture:

```text
OV9281 A -----                               Raspberry Pi 5
               /
OV9281 B -----/
```

Both cameras should use fixed known geometry and ideally external synchronization.

---

# 29. Development Stages

## Phase 1: Camera bring-up

Goal:

```text
640 x 400
RAW8
~300 FPS
```

Confirm:

- Camera works
- Stable FPS
- No dropped frames
- Manual exposure works

## Phase 2: Lighting

Record golf swings.

Confirm:

- Ball is sharp
- Clubhead is sharp
- No LED flicker
- Exposure is short enough

## Phase 3: Ring buffer

Implement:

- Circular RAM buffer
- Frame timestamps
- Manual trigger

## Phase 4: Impact trigger

Add:

- Piezo or microphone
- GPIO trigger
- Debounce/filtering

## Phase 5: Impact frame detection

Detect:

```text
first frame where stationary ball moves
```

## Phase 6: Calibration

Implement:

- Checkerboard/ArUco/AprilTag
- Pixel-to-world mapping
- Distortion correction

## Phase 7: Ball tracking

Output:

```text
X
Y
timestamp
confidence
```

for each frame.

## Phase 8: Ball speed

Calculate calibrated initial ball speed.

This is the first major milestone.

## Phase 9: Club tracking

Track clubhead before impact.

## Phase 10: Club speed

Calculate:

- Club speed
- Smash factor

## Phase 11: Launch

Estimate:

- Launch angle
- Start direction

## Phase 12: Impact location

Estimate clubface contact position.

Validate with impact tape or spray.

## Phase 13: Debug/replay tools

Build:

- Shot viewer
- Frame stepping
- Detection overlays
- Batch replay

## Phase 14: Phone app

Move:

- UI
- Shot history
- Heavy processing
- Calibration workflow

to phone if useful.

---

# 30. Validation

Validate each measurement separately.

## Spatial calibration

Move an object exactly:

```text
100 mm
```

System should report approximately:

```text
100 mm
```

## Ball speed

Compare against:

- Commercial launch monitor
- Known reference system

## Club speed

Compare against a trusted launch monitor.

## Impact location

Use:

- Impact tape
- Foot spray
- Strike stickers

Compare physical mark with camera estimate.

---

# 31. Initial Accuracy Goals

V1:

```text
Ball speed:       ±2 to 3%
Club speed:       ±3 to 5%
Smash factor:     ±0.05
Impact location:  ±10 mm
Launch angle:     ±2 to 3 degrees
```

Later target:

```text
Ball speed:       <1 to 2%
Club speed:       <2%
Impact location:  <5 mm
Launch angle:     <1 to 2 degrees
```

---

# 32. V1 Result Screen

Example:

```text
SHOT #27

BALL SPEED
61.8 m/s

CLUB SPEED
42.4 m/s

SMASH
1.46

LAUNCH
14.2 degrees

START
1.8 degrees RIGHT

STRIKE

┌───────────────────┐
│                   │
│          X        │
│                   │
└───────────────────┘

7 mm TOE
2 mm HIGH
```

---

# 33. Enclosure Concept

Front:

```text
┌────────────────────────────┐
│                            │
│   LED      CAMERA      LED │
│             O              │
│                            │
│        STATUS LIGHT        │
│                            │
└────────────────────────────┘
```

Inside:

```text
OV9281
Raspberry Pi 5 1GB
Active cooler
Impact sensor
LED driver
Power regulation
```

Camera must have a replaceable protective clear polycarbonate window.

Leave room for a second camera.

---

# 34. Important Design Rules

1. Capture first. Process second.
2. Keep raw frames during development.
3. Use real timestamps, not assumed FPS.
4. Use fixed manual exposure.
5. Avoid automatic camera settings during shots.
6. Use strong consistent lighting.
7. Keep camera position mechanically fixed.
8. Calibrate physical geometry.
9. Track over multiple frames instead of comparing only two.
10. Make every calculated detection visually inspectable.
11. Start with classical CV before machine learning.
12. Validate every metric against a known reference.
13. Do not add carry/spin calculations before speed and impact data are reliable.

---

# 35. First Milestone

The first meaningful prototype is:

```text
OV9281
640 x 400
~300 FPS
short exposure
rolling RAM buffer
manual shot trigger
raw frame replay
ball tracking
ball speed
```

Do not build the full UI before this works.

Once accurate ball speed works repeatedly, add club tracking.

---

# 36. V1 Definition of Done

V1 is complete when the system can repeatedly:

1. Detect a shot.
2. Capture the full impact sequence without dropped frames.
3. Identify the true impact frame.
4. Track the ball after impact.
5. Track the clubhead before impact.
6. Calculate ball speed.
7. Calculate club speed.
8. Calculate smash factor.
9. Estimate launch angle.
10. Estimate start direction.
11. Estimate strike location.
12. Save the shot for replay.
13. Show detection overlays for debugging.
14. Return to READY automatically for the next shot.

