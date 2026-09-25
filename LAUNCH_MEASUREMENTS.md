# Update: App 3.8.2 / Pi 0.26.0 — stored ground pose

Explicit ground calibration now permits tag removal. Reset empty plane requires recalibration with the tag. See raspberry_pi/README.md for the current flow.

# AprilTag launch measurements — app 3.16.0 / Pi 0.36.0

This release implements monocular and calibrated stereo measurement paths. Values derived from camera geometry are **estimates** until checked against a reference launch monitor. Missing evidence produces an unavailable value with a reason.

Current 3.16.0 behavior: three geometrically matched stereo frames spanning at
least 8 ms can provide a speed **estimate**; six are required for measured-grade
status. A camera capture becomes an app shot only when its speed, launch, and
direction come from camera measurements. If tracking fails, these values stay
unavailable, no club-profile ball speed is substituted, and nothing is sent to
the simulator. The app reports matched frame indices and failed quality checks.
The Pi's numeric `confidence` is an uncalibrated quality score, not a percentage
chance of correct tracking or speed accuracy, so it is not shown as a percentage
for camera shots.

Valid stereo fits are preferred over a successful single-camera fit. Stereo
geometry failures stay visible and force the remaining single-camera result to
estimated status. The app names the actual measurement source. Since 3.35.0 a
measured ball without a resolved club track is still a shot, with club values
unavailable; only movement classified `not-a-strike` (under 2 m/s, over 60° off
line, or a roll with no club) is excluded. This is evidence
of a swing near departure, not direct proof of face contact. Ground recalibration
invalidates a saved target line, since it may rotate the coordinate system.

## Pipeline and metrics

Sensor-timestamped grayscale burst → resting-ball position and camera poses → primary trajectory and ball-outline analysis. When that fit fails, each calibrated camera detects ball-sized circles independently. Candidates are paired by ray geometry, apparent size and a coherent 3D path; a joint fit recovers speed, launch and direction without using apparent ball size for depth. Stereo needs both lens calibrations and saved ground-tag poses from the same fixed tag placement. Three paired frames spanning at least 8 ms are eligible for measured-grade status when every timing, geometry, calibration, and fit-quality gate passes. Pair offsets must be ≤250 μs, median ray gap ≤3 mm, resting-height error ≤5 mm, start-anchor error ≤30 mm, and reprojection residual ≤3 px. Failure of a required geometry gate leaves metrics unavailable; failing a stricter grading gate leaves them estimated. Ground-tag pose error above 3 px is rejected. The sampled presence detector supplies only `coarseDepartureFrameIndex`; the last stationary and first coherent moving observations bound contact.

| Metric | Implemented method | Required evidence |
| --- | --- | --- |
| Ball speed | Fit velocity through monocular sphere centers or at least three paired stereo centers; three clean pairs can receive measured-grade status | Resolved ball positions and valid sensor timestamps |
| Launch / start direction | Vertical/horizontal angles of the fitted 3D velocity; start direction is measured against the calibrated target line (`/var/lib/pinpoint/target-line.json`, set from a ball rolled toward the target), not the tag's orientation | Ground tag lying flat; a target line for start direction (speed and launch angle do not need one) |
| Club / putter speed | AprilTag pose transformed to calibrated face center, then velocity regression | ≥3 pre-impact club-tag observations and correct club-specific rigid transform |
| Smash | Ball speed / club speed | Both accepted speeds |
| Strike toe/high | Ball relative to extrapolated face axes near departure; contact-plane proximity check | Face geometry, stationary ball observation, club pose within 10 ms |
| Backspin / spin axis | Optical-flow surface marks → ray/sphere intersection → rigid surface rotation | ≥3 nondegenerate marks, forward/backward flow agreement, ≥2 consistent pairs and <60° rotation per pair |
| Carry, total, apex, landing angle, offline | Still-air drag/lift model fitted to Trackman PGA Tour averages (carry within 1-7% driver to wedge), then a slide-to-roll turf model for roll | Accepted speed, launch and direction; spin from camera, else estimated from club speed and attack angle, else the club average. Excludes wind, terrain, curvature |
| Dynamic loft, spin loft | Rolling-contact impact model: launch minus attack angle fixes spin loft | Measured launch and attack angle; unavailable when launch exceeds attack by more than 40° |
| Putting roll distance | Straight-line placement-to-stop displacement on ground | Continuous ball visibility, ground-height consistency, ≥100 ms observed stop |
| Skid distance | Displacement until three consecutive low-slip translation/rotation pairs | Ground track and simultaneous resolved surface rotation |

Partial values appear automatically in the capture card on Monitor, Putting and Sessions. The Pi's legacy shot/putt message still requires all seven core values (speed, club speed, smash, launch, direction, strike X/Y). The app creates a camera shot only when camera-derived speed, launch and direction are all available; missing ball speed remains a failed capture, never a club-profile shot. Optional spin/carry/roll/skid fields are included only when available. `measurementSource` identifies camera estimates. Ball size in the trajectory fit comes from a sub-pixel edge fit (`ball_edge_fit`), and its comparison with the standard ball is a grading check.

Each reported value is graded by `grade_metrics`: `measured` means every applicable device quality gate passed, not that accuracy was validated against a reference launch monitor. Stereo checks include both pose errors, reprojection residual, ray gap, resting height, start anchor, pair timing, paired-frame count, and fit uncertainty. Anything else is `estimated`, with a `checks` list naming failed gates. The legacy `confidence` field multiplies gate penalties; it is an uncalibrated quality score, not the probability that the ball was tracked or that speed is accurate. The app shows Measured/Estimated labels and individual checks, not that percentage, on camera shots. Carry, face contact, roll/skid, and tag-free club values remain estimates.

## Physical setup needed

1. Keep the existing OV9281 rigidly mounted and focused. Use its **actual sensor timestamps**, fixed short exposure and enough light. The software rejects exposure above 250 µs and rejects estimated blur above 4 mm; at a hypothetical 70 m/s, 4 mm requires exposure below about 57 µs. This is a calculation, not a lighting specification.
2. Calibrate intrinsics/distortion for both cameras at exactly the capture resolution, sensor crop and lens focus. The ground AprilTag alone cannot determine lens parameters.
3. Print the supplied ID 0 ground tag at 100 mm black outer-edge size. Keep it fixed, flat, visible to both cameras and outside the swing path/detection region. Its decoded top edge points downrange. After lens calibration, use **Capture AprilTag calibration** with both cameras seeing the same tag; verify that both camera poses are saved. The shared tag frame establishes their relative geometry. Then you may remove it while both cameras and the surface remain fixed. Empty-plane reset invalidates saved poses and target line.
4. Attach a different tag (supplied ID 1, 20 mm) rigidly to the club where the camera can see it before contact. It must not interfere with the face or change position relative to the head. Size is a starting template, not a guarantee it will resolve at your speed/distance. Measure its transform for each club; do not reuse a driver's transform for an iron.
5. Use a ball with distinct, nonrepeating visible surface marks for spin. A plain silhouette cannot reveal rotation. The pipeline assumes radius 21.335 mm; actual ball size/deformation and image threshold bias affect depth.
6. For complete putting distance, keep the ball visible until stopped. The current burst tracker examines up to 256 post-departure frames. Longer putts outside that field/time window will correctly remain unavailable.

**Recommended next hardware step:** a second externally synchronized global-shutter camera for more reliable depth and occlusion coverage. An independently timestamped impact sensor would help reject hand-lift events. A ground tag plus a single image cannot guarantee exact club contact. Do not purchase a specific camera solely from this document; choose a supported synchronized pair after checking the required frame rate, exposure and field of view with your fastest shot.

## Lens calibration

Collect at least 12 images of a checkerboard with diverse tilts and positions covering the image, at the exact capture mode and fixed focus. The dimensions below count INNER corners. Measure the square size; replace the example values with the actual board.

```text
python scripts/calibrate-lens.py calibration-images --columns 9 --rows 6 --square-mm 20 --output intrinsics.json
```

Copy the accepted file to `/var/lib/pinpoint/intrinsics.json`, or set `PINPOINT_INTRINSICS_PATH`. The script rejects reprojection RMS above 0.7 pixels; low RMS alone does not establish absolute accuracy. Verify known distances across the hitting volume, not only on the tag plane. Changing focus, crop, sensor mode or resolution requires recalibration.

## Club calibration file

Create `/var/lib/pinpoint/club-marker.json` (or `PINPOINT_CLUB_MARKER_PATH`). This example is a **schema illustration, not usable measured geometry**:

```json
{
  "clubId": "driver",
  "tagId": 1,
  "tagSizeMm": 20,
  "faceCenterM": [0.01, -0.01, -0.03],
  "faceAxes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
}
```

Replace the position and axes with measurements for the actual mounting. Position is face center in tag-local metres; columns of `faceAxes` are unit toe, high and outward-normal vectors expressed in tag coordinates. The basis must be orthonormal and right handed. Match `clubId` to the selected app club (`putter` in putting mode). Unsupported or mismatched geometry blocks club and strike values.

## Target line

Start direction is measured against a target line. By default this now comes from the **camera's own across-image axis**, projected onto the ground from the calibrated pose: with the monitor squared to the target, the ball's line is whatever runs left to right across the image, so no calibration step is needed. This is taken from the camera pose rather than the tag, so it is unaffected by how the ground tag happens to be rotated. `diagnostics.calibration.targetHeadingSource` reports `camera-axis` when this is used.

Rolling a ball and using **Set target line** still saves an explicit heading, and an explicit line takes precedence (`targetHeadingSource: rolled-ball`). Clearing it returns to the camera axis rather than making start direction unavailable. The only case with no target line at all is a camera rolled towards portrait, where the across-image axis has no ground direction; level the monitor or save an explicit line.

## Tag-free club measurement

**Two cameras (preferred, 0.47.0).** The clubhead is dark against the mat, but the lit shaft and hosel highlight form a "check" whose lowest point, the hosel, is one physical point in both views. It is triangulated per frame (rays must meet within 10 mm), the longest run that one smooth path explains within 10 mm is kept, and its velocity at the last frame before impact gives `clubSpeedMps`, `attackAngleDeg` and `clubPathDeg`. Three frames are the minimum; five or more add a constant-acceleration term for the swing arc. The hosel moves slightly slower than the face centre. The single-camera swing-plane method below remains the fallback when the pair is not calibrated or the stereo track fails; on real chips it read about 20% low.

**Single camera (fallback).**

When no `club-marker.json` exists, the analysis falls back to tracking the clubhead silhouette. A monocular view cannot scale an unknown shape, so this path borrows scale from geometry that is already known: the head is back-projected onto a vertical swing plane pinned to the ball's position at contact, using the ball's own outgoing direction for the plane. It yields `clubSpeedMps`, `smashFactor` and `attackAngleDeg` as **estimates**, each naming its assumption.

`clubPathDeg` is deliberately **not** produced by this path. The swing plane is constructed from the ball's horizontal direction, so a club heading read off that plane equals the ball's start direction exactly, by construction. It would look like an independent measurement while restating one that already exists. Horizontal club direction needs depth the silhouette cannot supply, so it stays unavailable until a club tag or a second camera is present. Attack angle survives the same objection because the plane is vertical and does not constrain vertical motion.

This requires the camera to look **across** the swing, not along it. A camera whose rays lie inside the swing plane cannot resolve clubhead depth at all; that geometry is refused with a message rather than answered, and no amount of lighting fixes it.

Face contact needs one more number that a silhouette cannot supply: how wide the clubhead actually is. Measure the face once per club and save `/var/lib/pinpoint/club-profile.json` (or `PINPOINT_CLUB_PROFILE_PATH`). No tag and no mounting are involved:

```json
{
  "version": 1,
  "clubId": "sand-wedge",
  "faceWidthMm": 82,
  "faceHeightMm": 48
}
```

`faceWidthMm` is the heel-toe width, `faceHeightMm` the sole-to-crown face height. With the profile present, `strikeXmm`/`strikeYmm` are derived in the contact frame using the ball's known 42.67 mm diameter as the local scale reference, since ball and contact patch sit at the same depth. The measured face span is cross-checked against the profile, so a profile for the wrong club is rejected rather than applied. Without the profile both stay unavailable with a reason; they are never filled from a club profile.

Accuracy of the tag-free path has not been established against any reference. Attack angle is the most sensitive to the swing-plane assumption and should be the last value trusted.

Print-ready SVGs are in `output/measurement-targets-3.4.0`. Regenerate with `python scripts/create-measurement-targets.py`. Measure the black outer square and 100 mm ruler after printing.

## Install and acceptance

Run the existing Pi installer; it also installs `launch_measurements.py`. Keep automatic detection enabled. Deploy app 3.8.0/build 39, configure lens/club files and fixed exposure, then restart the service.

First validate slow motion at known distances. Then test actual strikes against an independent launch monitor and impact tape. Check image overlays, missed detections, false ball identity, ball-depth bias, club-pose ambiguity and spin aliasing. Test each club separately. Reject unsupported metrics rather than adjusting constants until they look plausible.

Known remaining engineering risks: analysis/JPEG saving still pause the acquisition worker; long occlusion can overwrite the trigger interval; brightness-based silhouettes can merge with the background; single-tag planar pose can be ambiguous; surface-flow rotation can alias or follow wrong marks; face extrapolation is not exact compression-time contact; full ball roll often exceeds the current capture window. The spin and roll/skid algorithms need real marked-ball footage before accuracy claims. A second-camera acquisition/synchronization pipeline is **not** implemented in this release.

## Evidence and references

Tests exercise off-axis sphere geometry, tag-pose round trips, known nonuniform-time velocity, surface rotation, sensor metadata, calibration rejection, a rendered moving-ball burst, core-result delivery and mismatched-club rejection. These are algorithm/software checks, not real-shot validation.

Verification for 3.4.0: 69 Python tests passed, including club speed/contact geometry and observed stop/skid fixtures. Fragmented-BLE client and OpenGolfSim bridge integration tests passed. TypeScript, ESLint and production web export passed. No real Pi/camera deployment, native-screen visual verification or real golf strike was performed.

Primary documentation: [OpenCV calibration and 3D reconstruction](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) and [Picamera2 sensor metadata](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf). [Raspberry Pi camera documentation](https://www.raspberrypi.com/documentation/accessories/camera.html) explains short-exposure global-shutter capture and its lighting requirement.
