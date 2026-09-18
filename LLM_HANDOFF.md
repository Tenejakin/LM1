# LM1 launch monitor — LLM takeover handoff

Document version: **1.0.3**  
Written: **2026-09-14**  
Workspace: **G:\Developemnt\LM1**  
Current app: **3.8.0**, native build **39**  
Pi service: **0.23.0**  
BLE protocol: **2.17.0**

## 1. Read this first

The user wants a working golf launch monitor that automatically detects a placed ball, waits for a strike, captures the sequence, calculates all defined measurements, displays them in the app, and provides a real image/replay of the strike.

**The code now contains experimental measurement algorithms. It is NOT a physically validated, complete launch monitor.** Synthetic geometry tests passed; no actual strike, current Pi deployment, native UI visual test, or accuracy comparison was performed during this conversation. Do not confuse implemented algorithms with demonstrated hardware performance.

Do not fabricate missing values or fill them from club profiles. Every camera metric must remain estimated/unavailable until justified by evidence. Existing demo/link-test generators are explicitly synthetic and separate from camera analysis.

The most recent user request is to create this handoff document so another LLM can take over. They previously authorized changing any part of the system to achieve the measurement objective and asked to be told what additional hardware/setup is necessary.

### User instructions and workspace handling

- User instruction: “Always udpate version on whatever you are doing. If its a wordpress plugin do everything so it can update as a plugin.” This repository is an Expo/Python launch monitor, not a WordPress plugin.
- This document has its own version; writing it does not change the 3.4.0 application runtime.
- For runtime releases synchronize `package.json`, root/package versions in `package-lock.json`, `app.json` version, iOS build number and Android version code. Update service/protocol constants as appropriate and the changelog/docs.
- The workspace already had extensive uncommitted and untracked work before these changes. Preserve it. **Do not reset, clean, discard, or infer ownership of all changes from `git diff`.**
- Many essential Python modules and test files are currently untracked. A handoff consisting only of a Git diff would omit them. Transfer the actual workspace or deliberately stage/review all required files before packaging.
- Development environment is Windows/PowerShell. Deployment is Linux/Raspberry Pi. Do not assume the Windows test installation matches Pi OpenCV/Picamera2 versions.

## 2. User conversation and outstanding physical questions

1. User requested a complete automatic capture/results workflow and an issue report.
2. Investigation found that camera ball removal previously generated synthetic speed, angle and strike coordinates. App 3.3.0 separated capture evidence from fabricated demo metrics.
3. User explicitly requested full launch measurements using AprilTags, allowed any changes, and asked what additional equipment was required. App 3.4.0 added monocular estimation algorithms and evidence gates.
4. User asked what is lost without a club tag. Answer: club/putter speed, smash factor, and face strike X/Y. Ball metrics and capture imagery can still be available, with appropriate calibration/visibility. Without all core fields, results stay in capture analysis and are not admitted to normal shot statistics.
5. User cannot place a tag on the hitting face. Explained that it can be elsewhere on the rigid head if visible: driver crown, iron back or putter top/rear, depending on camera angle. A calibrated transform relates the tag to the face. Do not wrap a flat tag around a shaft or curved head surface.
6. No actual club-at-address photo was provided, so **no specific mounting location has been verified**. The latest suggestion was to inspect a photo from the launch monitor's viewpoint to determine feasibility.

Do not assume a club tag, marked ball, lens calibration or calibrated face transform is already available on the real device.

## 3. Architecture and file map

### Raspberry Pi

| File | Role |
| --- | --- |
| `raspberry_pi/pinpoint_ble.py` | BLE peripheral, serialized notification writes, background camera monitor, thread-to-asyncio event forwarding |
| `raspberry_pi/pinpoint_protocol.py` | Commands, state machine, histories, capture events, conversion to shot/putt contract, explicit synthetic test results |
| `raspberry_pi/camera_source.py` | Picamera2 CSI camera ownership, `capture_request`, frame metadata and live diagnostics; `CsiCapture.read()` returns frame and retains metadata |
| `raspberry_pi/ball_detector.py` | Empty-background calibration, presence debounce, rolling buffer, departure capture, false-removal comparison, evidence analysis, saving/pruning/replay |
| `raspberry_pi/apriltag_calibration.py` | Preview AprilTag detection and saved planar image-to-mm homography; this alone is NOT lens or airborne 3D calibration |
| `raspberry_pi/launch_measurements.py` | Experimental lens/pose/sphere/club/spin/roll measurement functions |
| `raspberry_pi/wifi_manager.py` | Existing BLE-driven Wi-Fi setup |
| `raspberry_pi/install.sh` | Installs service modules, including `launch_measurements.py`, dependencies and configuration |
| `raspberry_pi/systemd/pinpoint.service` | Service unit; `/opt/pinpoint`, environment `/etc/default/pinpoint`, writable `/var/lib/pinpoint` |
| `raspberry_pi/tests/` | Protocol, detector, camera, calibration, Wi-Fi and measurement regressions |

### App

| File | Role |
| --- | --- |
| `src/types.ts` | Shot/Putt/DeviceStatus/DeviceEvent and CaptureAnalysis contracts |
| `src/services/device.ts` | BLE request/response client, newline JSON reassembly, unsolicited error forwarding, `listCaptures` and `captureFrame` |
| `src/services/bleTransport.native.ts` | Native BLE adapter; web uses a separate fallback and cannot validate real BLE |
| `src/context/LaunchMonitorContext.tsx` | Connection/reconnect, device events, captures, shots/putts, selected club, simulator forwarding |
| `src/components/CaptureReview.tsx` | Automatic image, adjacent-frame replay, per-metric values/reasons, capture history selection |
| `src/components/ShotDetailModal.tsx` | Existing complete-shot detail/replay and unvalidated-estimate labels |
| `src/components/ShotVisuals.tsx` | Existing diagrams and shot rows; drawn clubface position is not a captured photo |
| `src/screens/HomeScreen.tsx` | Automatic capture state and latest complete shot/capture |
| `src/screens/PuttingScreen.tsx` | Putting controls, capture card and putt metrics |
| `src/screens/HistoryScreen.tsx` | Existing shot statistics plus camera capture history |
| `src/screens/CalibrationScreen.tsx` | Live preview, empty-plane reset and planar tag save; explains additional lens/club calibration |
| `src/utils/carry.ts` | Existing separate club-factor carry fallback; camera results can supply their own explicit ballistic estimate |
| `src/services/opengolfsim.ts`, `src/context/OpenGolfSimContext.tsx` | Existing simulator integration; review forwarding policy for unvalidated estimates |

The app is React Native/Expo SDK 54, TypeScript, with native BLE. It uses m/s internally but predominantly displays km/h. A native development build is needed for BLE; Expo Go/web export is not a hardware test.

## 4. Capture flow

1. `BallMonitor.run()` owns the CSI/USB stream.
2. Detector learns an empty background. A ball present during this learning period can become background; remove it and reset calibration.
3. Repeated matching compact contours inside the ROI establish stable presence. The monitor emits `BallEvent(present=True)`.
4. `PinpointProtocol.ball_presence_changed()` sends presence and moves ready → armed.
5. Frames continue accumulating. `RollingFrameBuffer` keeps grayscale frame copies and a parallel bounded metadata deque.
6. On initial apparent disappearance, the monitor records a suspected departure timestamp. Debounce and scene-busy handling delay final removal.
7. After removal, collect configured post-impact frames. Compare the last armed-ball template against the final image. Detector-coordinate bounds are explicitly scaled into full-resolution coordinates. A matching ball restores presence instead of accepting removal.
8. `analyze_departure()` creates image evidence and calls `measure_launch()`. A recovered motion onset may refine the estimated departure index before saving.
9. Save a burst folder, then emit a false-presence `BallEvent` carrying analysis, capture ID and timing.
10. Protocol transitions to processing, saves `analysis.json`, sends a compact `capture` event with image and per-metric results, and may also emit a complete `shot`/`putt`.
11. Return to ready, or armed if a replacement ball was observed during result transfer.

**Important timing limitation:** analysis and JPEG saving still execute synchronously in the camera worker before the protocol receives the finished analysis. “Processing” is not displayed throughout all that work, and acquisition pauses. Decoupling acquisition from processing is a high-priority follow-up.

### Storage

Default root `/var/lib/pinpoint/rolling-captures`, configurable with `PINPOINT_ROLLING_CAPTURE_PATH`:

```text
capture-<timestamp>/
  frame-0000.jpg ...
  contact-sheet.jpg
  capture.json
  analysis.json
```

- `capture.json`: frame count, relative frame times, timestamp source, retained exposure/sensor metadata, observed FPS, estimated impact index and optional saved planar tag calibration.
- `analysis.json`: capture result, image and full measurement traces.
- Latest ten burst folders retained; older ones pruned.
- Capture analyses are restored from disk at service startup. Normal shot/putt histories have separate behavior; verify restart reconstruction if required.
- The app does not provide durable phone-side capture archival.
- Initial displayed image is a bounded, annotated frame just before estimated departure. It is **not proof of exact ball compression or club contact**.

## 5. Calibration and coordinate systems

There are three distinct calibrations. Do not conflate them:

1. **Empty scene:** presence detector background.
2. **Lens intrinsics/distortion:** exact resolution/crop/focus, from diverse checkerboard images.
3. **Physical pose/geometry:** ground tag establishes world coordinates; club tag has a separately measured rigid transform to face center and face axes.

### Ground tag

- AprilTag family `tag36h11`; default ID 0, black outer-edge size 100 mm.
- `launch_measurements.marker_map()` re-detects it in the current burst. A previously saved homography is not sufficient for this pipeline.
- Must stay visible, flat, fixed and outside the swing path.
- `tag_pose()` object corners are `[0,0,0], [s,0,0], [s,-s,0], [0,-s,0]` in metres.
- Intended world: +X target direction, +Y left, +Z up. App start direction is positive right, hence negative `atan2(v_y,v_x)`.
- Verify decoded corner order and axis convention against the actual installed OpenCV version and physical tag; do not infer orientation from an arbitrary rotated printout.

### Intrinsics

Default `/var/lib/pinpoint/intrinsics.json`, override `PINPOINT_INTRINSICS_PATH`.

```json
{
  "version": 1,
  "imageSize": [1280, 800],
  "cameraMatrix": [[800, 0, 640], [0, 800, 400], [0, 0, 1]],
  "distCoeffs": [0, 0, 0, 0, 0],
  "rmsPx": 0.2
}
```

**Numbers above are illustrative only. Never deploy them as calibration.**

Generate actual data with `scripts/calibrate-lens.py`. It requires ≥12 readable checkerboard views and RMS ≤0.7 px. Resolution mismatch is rejected. Resolution equality alone does not detect a changed sensor crop or focus: improve calibration identity checking.

### Club tag

Default `/var/lib/pinpoint/club-marker.json`, override `PINPOINT_CLUB_MARKER_PATH`.

- Fields: `clubId`, `tagId`, `tagSizeMm`, `faceCenterM`, `faceAxes`.
- `faceCenterM`: measured face center in tag-local metres.
- `faceAxes`: columns are toe, high, outward-normal unit vectors, expressed in tag coordinates; orthonormal, right handed.
- Club ID must match the selected app club; putting uses `putter`.
- Current implementation loads one configuration file, not a full per-club calibration library.
- A tag on crown/back/rear can work only if flat, rigid, unoccluded and large enough in the pre-impact images. No specific attachment has been validated.
- There is no guided club-transform calibration wizard. This remains a practical usability gap.

## 6. Measurement algorithms and limits

All current numerical camera outputs use status `estimated`. No measured accuracy/confidence model exists.

| Function / metric | Implementation | Key restrictions |
| --- | --- | --- |
| `sphere_center` | Undistort silhouette rays, fit tangent cone via SVD, derive sphere distance from known radius 21.335 mm, transform camera → world | Sensitive to contour, scale, deformation and lens error; monocular depth |
| `ball_contours` | Difference against a median of pre-departure frames (flicker-normalised), Otsu on the difference, size/fill/edge rejection | Needs the ball at rest for most of the pre-departure buffer; the ball must be brighter than what it moves over; not a trained robust object detector |
| Ball association | Nearest candidate with simple ambiguity, world-range and speed checks | Not a full motion-model/RANSAC tracker; identity switches remain possible |
| `fit_velocity` | Least squares over actual increasing timestamps; residual ≤8 mm | At least three observations; no calibrated uncertainty model |
| Speed/angles | 3D velocity norm and vertical/horizontal angles | Forward motion; ball speed 0.1–100 m/s; supported silhouettes required |
| Timing/exposure | Require all sensor timestamps, valid positive timing and exposure ≤250 µs; reject estimated blur >4 mm | USB host timestamps produce unavailable physical metrics |
| `measure_club` | Solve tag poses, transform face center, fit last 3–5 observations | Correct rigid transform and resolved pre-impact marker; 0.1–80 m/s |
| Smash | Ratio of ball/club speeds | Complete-shot converter requires 0 < smash ≤2.2 |
| Strike X/Y | Extrapolate last face position using velocity, project stationary ball into face axes | At most 10 ms extrapolation; contact-plane/range gate; orientation held constant during extrapolation |
| `measure_spin` | LK surface flow with reverse check; ray/sphere intersection; SVD rigid rotation; axis/rate from Rodrigues | ≥3 spread features, ≥2 consistent pairs, <60° per-pair rotation; aliasing still possible |
| Backspin | `-omega_world_y * 60/(2*pi)` | Signed: negative is topspin; audit consumers expecting nonnegative RPM |
| Spin axis | `atan2(omega_world_z, -omega_world_y)` | Sign/low-backspin behavior requires physical verification |
| Carry | Vacuum projectile range to launch height | No lift/drag/spin/wind; explicitly only a rough estimate |
| `measure_roll` | Ground-height and continuous-track checks, observed stop; straight-line displacement | Not curved path length; ball must stay visible until stop |
| Skid | Translation plus surface rotation → low contact-point slip for three pairs | Needs visible marks and continuous early motion; no full-shot-flight inference |

Tracking examines up to 256 frames after the initial candidate. The retained post-impact count may be much smaller (default 60). Raising only the tracker limit does not capture a longer putt.

The absence of a club tag blocks club speed, smash and face strike, but not ball estimates. The absence of ball marks blocks spin and usually skid, but not silhouette-based launch estimates.

## 7. Wire contract and result admission

- New `capture` event carries `CaptureAnalysis` with image, warnings, IDs, timing and optional `measurements`.
- `measurements.metrics` maps field names to `{ value: number | null, unit, status, reason }`.
- `_capture_summary()` removes detailed 3D/spin traces and template tracks from BLE. Full traces stay in disk `analysis.json`; this avoids oversized slow BLE history responses.
- `listCaptures` returns up to ten summaries with images; client timeout is 60 seconds. Verify payload/latency on actual hardware.
- `captureFrame` retrieves one compact frame by capture ID/index; errors when pruned/missing.
- Unsolicited wire `error` is mapped to app `captureError`, then shown in the error banner.
- Seven required values for `_measurement_result()`: `ballSpeedMps`, `clubSpeedMps`, `smashFactor`, `launchAngleDeg`, `startDirectionDeg`, `strikeXmm`, `strikeYmm`.
- If any is absent/nonfinite, no normal shot/putt event is emitted. The capture card still shows partial results.
- Complete results have `simulated: false`, `measurementSource: monocular-estimate`, and `confidence: 0` as an uncalibrated placeholder. Main/detail/putting labels handle this as unvalidated. Audit any other consumer of confidence.
- Putting renames club speed to `putterSpeedMps` and start direction to `launchDirectionDeg` for the existing contract.
- Optional values are included only when available.
- Existing simulator forwarding may automatically forward a complete estimate if the user has enabled auto-send. This policy was not redesigned or physically validated.

## 8. What was verified

Last recorded verification for runtime 3.4.0:

- **69 Python tests passed**, OpenCV enabled.
- `npm run test:capture` passed (fragmented BLE client contract).
- `npm run test:ogs` passed (OpenGolfSim bridge).
- `npm run typecheck` passed.
- `npm run lint` passed.
- Production web export succeeded in `output/launch-measurements-3.4.0`.
- Python compile and `git diff --check` passed.

These results were recorded during implementation, not rerun for this documentation-only handoff.

Key tests: `test_launch_measurements.py` checks off-axis sphere recovery, pose round trips, nonuniform timing, invalid tracks, surface rotation math, rendered moving-ball launch, club geometry and roll/skid fixtures. `test_capture_workflow.py` checks capture state, images, send failure, rearming, complete-result conversion and mismatched club calibration.

**Not verified:** real marked-ball optical flow across actual strikes, real club-marker readability/pose, end-to-end Pi performance, accuracy, current installation/environment, native UI, native BLE timing, long-session storage and complete putting capture. Synthetic test inputs must never be cited as measured real-world performance.

An older local contact sheet at `tmp/shot-analysis-1789048073958760120/contact-sheet.jpg` was viewed. It does not visibly establish a golf strike; it is not an accuracy-validation dataset. Other captures exist under `tmp/` and `camera-tests/`; inspect their provenance before using them.

## 9. Highest-priority takeover work

1. **Inspect actual hardware/configuration.** Establish camera mode, effective frame rate, exposure, focus, field of view, Pi RAM, tag visibility and device access. No current connection credentials/host were established in this task.
2. **Make physical calibration practical.** Provide acquisition guidance/tooling for lens views and a validated face-transform procedure/per-club store. Resolve club mounting from the real camera viewpoint.
3. **Decouple acquisition from analysis/storage.** Use a bounded processing queue and retained snapshot ownership. Measure dropped frames and memory. Do not block high-speed acquisition with tag detection, full-frame template matches or JPEG writes.
4. **Separate strike confirmation from removal.** Current candidate can be a hand lift. Add validated club/ball contact evidence or synchronized impact trigger, with false-trigger tests.
5. **Validate ball identity and depth.** Test silhouettes under blur, threshold bias, bright clutter, partial occlusion and multiple balls; add uncertainty/rejection rather than arbitrary tuning to expected speeds.
6. **Validate club and spin.** Actual pre-impact tag sequence; actual asymmetric marked-ball sequence. Audit coordinate handedness, corner ordering, spin signs, aliasing and contact extrapolation.
7. **Address fast-shot sampling limits.** At 70 m/s through 0.4 m, visibility is ~5.7 ms. At 200 FPS, reliable multiple outgoing samples are not guaranteed. Determine suitable FOV/frame rate from evidence; synchronized stereo is a possible hardware upgrade, not existing functionality.
8. **Rework partial-shot UX if desired.** Today no club tag means no normal statistical shot despite useful ball data. Do not insert zeroes to bypass required fields; redesign nullable/provenance-aware contracts if changing this.
9. **Extend putting acquisition.** Full roll often exceeds current time/FOV. Treat no observed stop as unavailable, not a fabricated distance.
10. **Run hardware acceptance.** Reference launch monitor for speeds/angles; impact tape for face position; controlled marked-ball rotation for spin. Record errors per metric and per club before accuracy claims.

Other audit targets: frame/metadata clock consistency; planar pose ambiguity; camera disconnect while processing; history hydration racing live events; service restart recovery of full shots; calibration validity after crop/focus changes; readable image resolution; retention/exports; generated result persistence and simulator provenance.

## 10. Commands and artifacts

Run from workspace root:

```text
python -m unittest discover -s raspberry_pi/tests -q
npm run typecheck
npm run lint
npm run test:capture
npm run test:ogs
npx expo export --platform web --output-dir output/<new-version-specific-directory>
```

Calibration/targets:

```text
python scripts/calibrate-lens.py calibration-images --columns 9 --rows 6 --square-mm 20 --output intrinsics.json
python scripts/create-measurement-targets.py
```

Checkerboard numbers are examples; use actual inner-corner counts and measured square size. No real lens calibration dataset was acquired here.

Printable SVGs:

- `output/measurement-targets-3.4.0/tag36h11-id0-100mm.svg`
- `output/measurement-targets-3.4.0/tag36h11-id1-20mm.svg`

Pi deployment: follow `raspberry_pi/README.md` and `install.sh`, including existing `--offline` option where prerequisites are satisfied. Service environment lives at `/etc/default/pinpoint`. Important settings: `PINPOINT_AUTO_BALL_DETECTION`, `PINPOINT_CAMERA_SOURCE`, `PINPOINT_CAMERA_RESOLUTION`, `PINPOINT_CAMERA_FPS`, `PINPOINT_EXPOSURE_US`, `PINPOINT_INTRINSICS_PATH`, `PINPOINT_CLUB_MARKER_PATH`, `PINPOINT_APRILTAG_ID`, `PINPOINT_APRILTAG_SIZE_MM`, `PINPOINT_BALL_ROI`, `PINPOINT_PRE_IMPACT_FRAMES`, `PINPOINT_POST_IMPACT_FRAMES` and `PINPOINT_ROLLING_CAPTURE_PATH`.

Read exact defaults and parsing from code rather than assuming a documented value matches the installed Pi. The installer historically retained a simulator backend setting while enabling automatic camera detection; `automaticCapture` and actual evidence now control the relevant path.

## 11. Reading order and documentation cautions

1. This handoff.
2. `LAUNCH_MEASUREMENTS.md` — current setup and supported algorithm paths.
3. `launch_measurements.py`, `test_launch_measurements.py` — actual math and limits.
4. `ball_detector.py`, `camera_source.py`, `pinpoint_protocol.py` — live integration.
5. App types/context/capture component — UI and contracts.
6. `DEVICE_API.md`, `raspberry_pi/README.md`, `CHANGELOG.md`.
7. `golf_launch_monitor_project.md` — original goals and design, **not proof of implemented capability**.
8. `CAPTURE_WORKFLOW.md` — historical 3.3.0 issue report; its no-measurement-pipeline statements were superseded by 3.4.0, but many capture risks remain.

Older README/API paragraphs may describe synthetic test behavior. Resolve contradictions against the current source and this distinction: experimental camera estimates vs explicit synthetic demo results vs physically validated measurements (not yet demonstrated).

## Suggested initial prompt for the successor LLM

> Read LLM_HANDOFF.md and inspect the referenced current source without discarding uncommitted work. Continue toward a physically working, AprilTag-calibrated launch monitor. First verify the real camera/setup and the practical club-tag mounting/calibration constraints. Preserve per-metric provenance and do not fabricate missing measurements. Prioritize uninterrupted capture, real strike confirmation, actual calibration and reference validation. The passing synthetic tests establish software behavior only. Keep versions synchronized and report every material limitation clearly.
