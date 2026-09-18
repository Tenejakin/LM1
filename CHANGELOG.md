# Changelog

## App 3.11.0 / Pi service 0.28.0 - 2026-09-18

Usability pass over the app, plus automatic exposure.

- Automatic exposure: `autoCalibrateExposure` measures the room and picks both shutter and gain. The sweep probes a spread of shutter speeds at 1× gain, scores each frame on mean brightness and clipping, and keeps the **shortest** exposure that is still bright enough — motion blur costs more accuracy than grain does. Only when every allowed exposure is still dark does it raise analogue gain. The result is applied and persisted exactly as a manual change would be.
- The sweep runs inside the detection loop and borrows that loop's own frames, so it never opens a second handle on the camera or races the detector. Afterwards the empty-plane calibration is reset, because the new exposure changes what "empty" looks like.
- Manual shutter and gain controls are unchanged. Automatic exposure is a starting point, not a replacement, and a manual change overrides it at any time.
- Accuracy note: the target brightness (mid-grey, under 2% clipped pixels) is a reasonable default, not a validated optimum for ball tracking. It has not been checked against measurement accuracy on real shots.
- App: speeds and distances now follow a saved units preference (km/h or mph, metres or yards) applied across every screen. The calculator's own unit switch now sets that same preference instead of a second, screen-local one.
- App: the Device screen no longer shows every setting at once. Wi-Fi, simulator, automation, units and camera tuning fold away behind labelled sections with a status badge, leaving connection, health and the arm/trigger controls in the open.
- App: plainer wording throughout — "Start tracking" instead of "Arm launch monitor", "Shutter" and "Brightness boost" instead of "Exposure" and "Analogue gain", frames per second instead of raw FPS and microsecond readouts in the hero.
- App: the empty home screen is now a three-step checklist that ticks itself off, the error banner offers a route to the Device tab instead of only a dismiss, and disconnecting asks first.
- App: raised every sub-11px label to a readable size and enlarged the bottom tab targets.
- 32 new Pi tests (20 for the exposure search, 4 for the new command, plus frame measurement and planning); all 12 Pi test modules pass. TypeScript and lint pass.

## App 3.10.3 / Pi service 0.27.0 - 2026-09-18

- Clubhead speed, attack angle and club path no longer require an AprilTag on the club. The head silhouette is segmented from the existing motion background and back-projected onto a swing plane pinned to the ball at contact, which supplies the scale a monocular view cannot. Values are estimates and name the assumption carrying them.
- The tag path is unchanged and still preferred: `club-marker.json` takes precedence, and the silhouette path runs only when no club tag is calibrated.
- A camera looking along the swing instead of across it is refused rather than answered. Clubhead depth is not observable in that geometry, and the previous parallel-ray check let near-degenerate poses through.
- Head tracking selects the longest consecutive run of frames with a consistent silhouette, preferring the run nearest impact. A real head crosses lighting boundaries mid-swing and its segmented area can halve between frames; fitting across that step mixes two different features.
- Face contact (`strikeXmm`/`strikeYmm`) uses the ball's own 42.67 mm diameter as the scale reference in the contact frame, and additionally needs a one-off measured face size in `club-profile.json`. Without it both stay unavailable with a reason, never a club-profile substitute. A profile that disagrees with the measured face span is rejected.
- Start direction no longer needs the rolled-ball calibration. The target line now defaults to the camera's own across-image axis projected onto the ground, which is correct whenever the monitor is squared to the target, and is taken from the camera pose rather than the tag so tag rotation is irrelevant. A saved rolled-ball line still takes precedence, and clearing one returns to the camera axis instead of making start direction unavailable. `targetHeadingSource` records which was used.
- Added `clubPathDeg` and `attackAngleDeg` to the metric set; both flow through the existing capture record with no protocol change. Club path is produced only from a calibrated club tag: the silhouette path's swing plane is built from the ball's own direction, so a path read off it equals start direction by construction and would restate an existing measurement as an independent one. Attack angle is unaffected, because a vertical plane does not constrain vertical motion.
- Shaft lean is reported as a diagnostic only when enough shaft is resolved, instead of fitting a direction to a dozen stray points.
- App: smash factor no longer inherits the ball measurement's confidence when club speed is the club-profile fallback. In that case the ratio collapses to the profile's smash constant exactly, so it is labelled a club estimate at the weaker input's confidence.
- Replayed `capture-1789685046360385423` on the Pi: club speed 2.51 m/s over 5 accepted frames, 0.6 mm fit residual, smash 1.13 against the 2.83 m/s ball speed, start direction 1.03° against a camera-axis target line 0.29° off the tag. Attack angle reads -19.8°, steeper than expected for this chip and the least trustworthy value on the path. No value here has been checked against an independent reference.
- 149 Pi tests pass locally; TypeScript and lint pass.

## App 3.10.2 / Pi service 0.26.1 - 2026-09-17

- Extended manual OV9281 exposure control to 20–250 μs and added 20, 50 and 75 μs quick presets for stronger motion freezing. The camera may report a nearby value when sensor timing rounds the request.

## App 3.10.1 - 2026-09-17

- OpenGolfSim auto-send now forwards the same completed full-shot values displayed by the app. When camera metrics are unavailable, clearly-labelled club estimates fill the simulator payload instead of silently dropping the shot.
- Manual sending from Camera hit review uses the same completed estimated shot, and complete device shot events are deduplicated after their capture was already forwarded.

## App 3.10.0 - 2026-09-17

- Motion-tracked full-shot captures now open the shot review automatically, even when the camera could not resolve every metric.
- Missing values are estimated from the selected club and available ball/launch measurements. Smash factor derives from the best available ball and club speeds; spin uses the club baseline adjusted by launch angle.
- Shot review now labels individual values as measured, camera-estimated or club-estimated and shows a compact confidence percentage for each.

## App 3.9.1 - 2026-09-17

- Added n8n send controls to every Camera hit, including incomplete and departure-unconfirmed captures. Camera hits send the complete `CaptureAnalysis` record as a versioned `lm1.capture` event, while complete Shot log entries continue to use `lm1.shot`.

## App 3.9.0 - 2026-09-16

- Added a persisted n8n production-webhook setting in the Device tab. Each complete shot in Sessions now has an adjacent send button that posts the entire stored shot object in a versioned `lm1.shot` JSON envelope, with per-shot sending, success and error feedback.

## App 3.8.2 / Pi service 0.26.0 - 2026-09-16

- Explicit AprilTag calibration now saves a validated 3D ground pose and exact lens inputs. Shot analysis preferentially uses this stored geometry, allowing removal of the ground tag while the camera, focus, capture mode and hitting surface stay fixed. Diagnostics and metric reasons identify saved versus burst-derived pose. Old planar-only calibration requires a fresh capture before tag removal.
- Reset empty plane invalidates saved AprilTag geometry and target line. Successful lens recalibration also clears both; changed intrinsics, image size or tag dimensions reject reuse. Invalid calibration capture cannot overwrite an existing valid calibration. Visible tags retain the previous burst-derived fallback when no stored pose exists.
- App shows saved ground calibration after reconnect and explains tag removal and reset. Added stored-pose, tag-absent analysis, lens mismatch, invalidation and invalid-save tests. 120 Pi tests pass locally and on the Pi; TypeScript and lint pass locally.

## Pi service 0.25.0 - 2026-09-16

- Added single-frame bilateral denoising before departure tracking and measurement, including the armed reference. Original burst frames and displayed evidence remain unchanged. `PINPOINT_ANALYSIS_DENOISE=none` disables it; default is `bilateral` (diameter 5, sigma colour 12, sigma space 3). Capture diagnostics record filter parameters and processing time. No temporal averaging.
- Replayed capture-1789515451301879262 at 8x gain, 95 us actual exposure: raw 3.537 m/s versus filtered 3.5622 m/s, both 13 fitted frames and no spin. Tag pose error improves from 1.5514 to 1.3611 px; image fit barely changes (1.512 to 1.507 px), radius fit worsens (1.333 to 1.659 px). No claim of improved physical accuracy. JPEG replay differs from live pixels. Added noise/edge/raw-preservation regressions.

## Pi service 0.24.0 - 2026-09-15

- Added an anchored trajectory fit as the primary speed, launch-angle and direction estimator whenever at least six outgoing frames are tracked. It fits up to 48 frames in one model: the start point is the resting ball's ground position, sub-pixel image centres are weighted heavily, and apparent radius weakly. Earlier estimates came from 3–8 per-frame silhouette depths. Single-view depth error runs along the camera's line of sight, which rises about 24 degrees from the ball on the bench rig; this is the direction of the false 24-degree launch. A ground roll (with deceleration) and a gravity flight are both fitted. Flight is reported only when it explains the track clearly better and its launch exceeds three standard deviations.
- Balls moved before release (finger or clubhead nudges) fall back to a roll with a re-estimated ground start, provided its deceleration is physically plausible. One round of outlier rejection removes occluded frames. Per-shot `trajectoryFit` diagnostics record the model, start point, rejected frames, image and radius residuals, and fit uncertainties; metric reasons show fit ± values, which exclude lens and ground-tag calibration error. The fitted positions feed `ballTrack3d`, so Set target line uses the fitted roll direction. Tracks too short to fit keep the previous silhouette path.
- Template tracking now reports sub-pixel ball centres with parabolic peak interpolation, using a pixel-centre convention (previously whole pixels offset by half a pixel). Saved burst frames use JPEG quality 95 instead of 88, so offline replays stay closer to live analysis.
- Replays: `capture-1789479880648283083` 0.53 m/s, 0°, heading 91.7°, 1.6 px over 48 frames; `capture-1789480689809610280` 0.96 m/s, 0°, heading 68.8°, start re-estimated 37 mm from the nudged resting spot, 1.0 px; `capture-1789481235085592832` 0.86 m/s, 0°, heading 82.3°, start re-estimated 20 mm, two occluded frames rejected, 0.8 px. Analysis takes about one second locally. Values are unvalidated against an independent reference.
- Added tests for sub-pixel tracking, a rolling ball with a growing silhouette, an airborne launch with direction, a nudged start, occluded frames and the full measurement path. All 114 Pi tests pass locally.

## Pi service 0.23.6 - 2026-09-15

- Fixed contact analysis locking onto a hand that stays in view. A moving sequence now counts as the ball's departure only if it starts near the resting ball and the resting ball is not matched again afterwards. When several sequences qualify, the one nearest the debounced trigger wins, so an earlier finger nudge is not reported as the shot.
- Fixed a ball that armed while the placing hand still touched it. Analysis compares the armed image against the earliest burst frame and uses whichever finds the resting ball more cleanly. The monitor also refreshes the armed image while the ball stays within its arming bounds; a slow roll that shifts its bounds still keeps the original image.
- Replayed `capture-1789479880648283083`: first moving frame 157 (previously frame 17, hand matches, no measurement); ground-plane speed 0.54 m/s, consistent across 12- to 40-frame windows (the 3D-depth fit alone gave 0.71 m/s). Replayed `capture-1789480689809610280` with its saved hand-contaminated reference: first moving frame 191 (previously frame 138, a static lookalike, no measurement); 0.93 m/s along the ground. Speeds remain unvalidated against an independent reference.
- Fixed rolling balls reporting a launch angle. Single-view sphere depth follows apparent size, so a few percent of silhouette error moves a rolling ball's estimated centre up and down; `capture-1789481235085592832` read a 4% radius growth over frames 179–181 as a 24-degree launch at 2.23 m/s. When the fitted track stays within 20 mm of resting-ball height and rises less than 15 mm, the shot is reported as a ground roll: launch and carry are 0, and speed and start direction come from template-tracked ball-centre rays projected onto the ground plane. Captures record `groundRoll` evidence. Replays of all three rolls report 0 degrees; that capture measures 0.85 m/s along the ground.
- Added regressions for a moving lookalike while the ball rests, a contaminated armed reference, an early nudge before the roll, reference refresh while resting, a rolling ball with a growing silhouette and a rising ball that keeps its launch angle. All 108 Pi tests pass locally.

## Pi service 0.23.5 - 2026-09-15

- Fixed the rolling-ball reference becoming corrupted: the presence detector could continue accepting a slowly moving ball while its reference image was replaced and its original bounding box stayed fixed. The reference now remains paired with the arming bounds until disarm/reset. Each new capture preserves `armed-ball-reference.png` losslessly for replay.
- Replayed roll `capture-1789479880648283083` using its early stationary frame: the image track improves from three hand matches at frames 17–19 to 133 moving-ball matches at frames 157–289, with 11 strict 3D outlines and a provisional 0.71 m/s speed. The approximately 14-degree launch estimate is inconsistent with the intended ground roll and remains unvalidated.
- Added monitor-loop and lossless-reference regressions. All 102 tests pass locally and on the Pi.

## Pi service 0.23.4 / capture audit tool 1.0.0 - 2026-09-15

- Saved calibration inputs, inferred camera height/pitch, strict-outline counts and partial-outline rejection details with each capture. Failure messages distinguish captured frames, motion matches, accepted 3D outlines and consecutive sequences. Detailed diagnostics are excluded from Bluetooth summaries.
- Added a read-only capture audit script and a setup validation report under `output/capture-audit-v1.0.0`. Latest-shot replay confirms 325 frames at 241.57 fps, eight outgoing image matches, no accepted 3D sequence, brightness variation and about 22 cm of remaining ground-level travel in view.
- All 100 Pi tests pass locally and on the Pi. Experimental edge fitting remains an offline investigation; metric acceptance rules are unchanged.

## Camera target-line calibration tool 1.0.0 - 2026-09-15

- Added `scripts/set-camera-target-line.py` to project a left-to-right image line through the hitting position onto the calibrated ground plane and save its heading. Uses lens distortion correction and the newest capture's ground-tag pose; preserves the previous target line as a backup.

## Hardware bench prototype 0.5.1 - 2026-09-15

- Added a 28-degree downward camera bracket compatible with the v0.5.0 tray and mast. Only the bracket needs reprinting. Exported all three printable parts, assembly reference, preview and mesh validation report under `hardware/enclosure/stl/v0.5.1-test`.

## Pi service 0.23.3 / BLE protocol 2.17.0 - 2026-09-15

- Fixed contact analysis selecting frame 0 when a resting ball had shifted slightly from its placement bounds. Tracking now re-anchors to three strong nearby stationary observations and requires outward progress before accepting a moving sequence.
- Replayed capture `capture-1789475289749304965` (325 frames, 241.57 fps): the retained contact window resolves to stationary frame 164 and moving frame 166, rather than frame 0. The capture contains the contact window; the previous contact sheet selected the wrong frames.
- Added regressions for shifted resting balls and static template lookalikes. All 98 Pi tests pass. Camera frame rate and trigger debounce settings remain unchanged.

## 3.8.1 / Pi service 0.23.2 / BLE protocol 2.17.0 - 2026-09-14

- Fixed reconnects failing with “oversized Bluetooth message”: `listCaptures` now applies the existing ten-record history limit instead of serializing all 100 retained captures and their preview images. All captures remain stored on the Pi.

## 3.8.1 / Pi service 0.23.1 / BLE protocol 2.17.0 - 2026-09-14

- Expanded the default ball-detection region from 35% to 61.2% of the camera frame (`0.05,0.30,0.95,0.98`) for more flexible ball placement. Existing Pi installations retain their explicit `PINPOINT_BALL_ROI` setting; update it in `/etc/default/pinpoint`, then restart with the enlarged area empty.
- Added regression coverage for the expanded default region. App 3.8.1/build 40.

## 3.8.0 / Pi service 0.23.0 / BLE protocol 2.17.0 - 2026-09-14

- Added a guarded fallback for shots whose ball is tracked reliably but whose bright silhouette is partly clipped by the club, seams or background edges. The strict 0.82 fill path remains first; the fallback requires an independent template-track match, at least three consecutive frames, a stable apparent radius and the existing 8 mm 3D trajectory-fit limit.
- Replayed device capture `capture-1789392914021558544`: the original analyzer found 21 image-plane track points but zero accepted 3D silhouettes. The guarded fallback uses frames 162–164 and recovers a lower-confidence 6.33 m/s ball-speed estimate, 19.37° launch estimate and 2.56 m vacuum carry estimate with a 7.1 mm fit residual. Start direction remains unavailable until the target line is calibrated.
- New capture manifests retain `ballBounds`, so future saved bursts can be replayed with the exact armed-ball geometry instead of reconstructing it from logs.
- Added regression coverage for partial silhouettes and the three-consecutive-frame fallback guard. App 3.8.0/build 39.

## 3.7.3 / Pi service 0.22.0 / BLE protocol 2.17.0 - 2026-09-14

- Fixed captures that lost all launch data because the first visible ground AprilTag frame had a poor pose: compare up to 12 detections across the static burst and use the lowest reprojection-error pose.
- Keep the normal path at or below 1 px; allow 1–3 px only as an explicitly lower-confidence estimate with the exact error and source frame in capture metadata and metric provenance. Poses above 3 px remain rejected.
- Replayed `capture-1789337222749633794`: the original first pose failed at 2.31 px, while the new selector chose frame 445 at 0.0398 px and recovered a nine-point ball track plus ball speed, launch angle, start direction and carry estimates.
- App 3.7.3/build 38.

## 3.7.2 / Pi service 0.21.0 / BLE protocol 2.17.0 - 2026-09-14

- Fixed another "motion tracked, no data" case (capture-1789341264765340216): the ball was template-tracked across 40 frames, but no silhouette reached the depth fit. The dark seam line crossing the ball split the thresholded disc into two half-discs or cut a slit, so every blob failed the 0.82 fill test (fills 0.38–0.81). `ball_contours` now applies a 5 px elliptical close before contouring.
- Replayed with the real `measure_launch` on four Pi captures: the missed shot now gives 1.19 m/s from 16 silhouettes (2.0 mm residual); the previous seam shot improves from 7 to 15 silhouettes (1.23 m/s); an earlier good shot is unchanged (18 silhouettes, 1.27 vs 1.29 m/s); a hand-placement capture still yields no speed. Hull-area fill variants were rejected because they admitted lamp-flicker blobs at the resting position.
- Known limit: where the ball's top crosses the bright strip behind the mat, its silhouette is clipped and launch angle can be badly wrong (−21.8° on the missed shot) even though speed agrees across methods.
- App 3.7.2/build 37 (no app code changes).

## 3.7.1 / Pi service 0.20.0 / BLE protocol 2.17.0 - 2026-09-14

- Fixed ball-speed failures on shots whose motion was clearly tracked. On capture-1789340704201918915 the silhouette detector found clean ~35 px ball outlines in 13 outgoing frames, but the depth fit rejected all but one as "too small or distorted": the ball's dark seam line and shaded edge dent the thresholded outline, exceeding the cone-fit tolerance (1.05–1.77× the limit). `sphere_center` now fits the silhouette's convex hull points, which ignores those dents (0.18–0.61× the limit) while still rejecting stretched, merged or non-circular blobs.
- Replaying that capture on the Pi now yields a ball estimate from 7 frames: 1.19 m/s, launch −2.9°, 3.3 mm fit residual. A hull-area fill gate was evaluated and rejected because it admitted lamp-flicker blobs.
- App 3.7.1/build 36 (no app code changes).

## 3.7.0 / Pi service 0.19.0 / BLE protocol 2.17.0 - 2026-09-14

- Pi analysis was 5.9 s per shot on the Pi (profiled on capture-1789339832405469525); 4.6 s was full-resolution `matchTemplate` over all 270 frames. Ball tracking now searches at half resolution and re-scores a small full-resolution window, keeping the same score thresholds.
- BLE notifications were fixed 20-byte chunks every 15 ms (~1.3 KB/s): a capture event took ~3.7 s and a contact sheet ~24 s. The app now sends its negotiated MTU in the initial `status` request and the Pi sends `min(244, MTU - 3)`-byte chunks (~16 KB/s). App command writes also use MTU-sized chunks. Older apps that omit `mtu` keep 20-byte chunks.
- Camera preview notifications are skipped while a capture result is being delivered.
- App 3.7.0/build 35.

## 3.6.1 / Pi service 0.18.0 / BLE protocol 2.16.0 - 2026-09-14

- Shortened the rolling burst from 580 frames (~2.9 s with the Pi's `PINPOINT_PRE_IMPACT_FRAMES=400`) to 270 frames (~1.35 s): 120 pre-trigger, 120 removal-debounce and 30 post-removal frames. A struck ball crosses the view in ~40 ms and removal is confirmed ~0.5 s later, so the earlier ~2 s of pre-roll only fed the background median.
- Lowered the default `PINPOINT_DEPARTURE_TIMEOUT_SECONDS` from 1.0 to 0.5 so a forced removal still keeps the departure and resting-ball frames inside the shorter burst.
- Moved AprilTag detection, the focus metric, the camera snapshot write and BLE preview encoding to a background worker. Run inline every 3 s they stalled the camera loop 10–30 ms and dropped 200 fps frames in every retained burst, including one right at impact (capture-1789339311233490650, frame 420).
- Raised the Picamera2 request queue from 4 to 8 (`PINPOINT_CAMERA_BUFFER_COUNT`) to absorb remaining short stalls.
- About half the JPEG writes per capture, so results reach the app sooner and storage per burst drops by about half.
- App 3.6.1/build 34 (no app code changes).

## 3.6.0 / Pi service 0.17.0 / BLE protocol 2.16.0 - 2026-09-14

- Every camera capture card (Home, Putting, History) and every shot detail with a `captureId` now loads and shows that burst's 12-frame contact sheet automatically, with a retry on failure.
- Added BLE `captureContactSheet` (`captureId`) returning the saved `contact-sheet.jpg` of a specific retained burst; invalid or pruned captures return an error.
- Contact sheets are cached in the app for the session so reopening a shot does not re-transfer them.
- App 3.6.0/build 33.

## 3.5.4 / Pi service 0.16.4 / BLE protocol 2.15.4 - 2026-09-14

- Added live OV9281 analogue-gain control to the Device screen with decimal entry and 1×/2×/4×/8×/16× presets.
- Added BLE `setGain` plus sensor-derived `gainControl` capability metadata for the supported 1×–16× range.
- Persist exposure and gain together atomically; later exposure changes preserve the selected gain and both settings survive service restarts.
- Reject gain changes during automatic exposure, armed capture, or processing, and warn that higher gain adds image noise.
- App 3.5.4/build 32.

## 3.5.3 / Pi service 0.16.3 / BLE protocol 2.15.3 - 2026-09-13

- Added live manual OV9281 exposure control to the Device screen with numeric entry and 100/150/200/250 μs presets.
- Exposure updates apply without restarting the Pi service, persist atomically in `/var/lib/pinpoint/camera-settings.json`, and are restored after reboot.
- Limited app-controlled exposure to the measurement-safe 50–250 μs range and reject changes while armed or processing.
- Added BLE `setExposure` plus `exposureControl` capability metadata and focused Pi camera/protocol tests.
- App 3.5.3/build 31.

## 3.5.2 / Pi service 0.16.2 / BLE protocol 2.15.2 - 2026-09-13

- Separate the sampled/debounced `coarseDepartureFrameIndex` from `lastStationaryFrameIndex` and `firstMovingFrameIndex`; the backward-compatible `impactFrameIndex` now resolves to first observed motion when a coherent ball track exists.
- Track from the retained stable-ball image instead of the frame before the coarse trigger, which may already be empty, and require a coherent outward sequence to reject unrelated template matches.
- Capture manifests, frame replay responses, capture/shot events and app types now preserve all three markers. Replay shows the contact interval in orange and the later coarse trigger in gray.
- Added a regression for a ball that is already out of frame when the sampled departure trigger fires.
- App 3.5.2/build 30.

## 3.5.1 / Pi service 0.16.1 / BLE protocol 2.15.1 - 2026-09-13

- Increased rolling-capture retention from 10 to 100 complete bursts on the Pi, with one shared `PINPOINT_CAPTURE_RETENTION` setting used for disk pruning and restored/in-memory capture history.
- Added `captureId` to every `capture.json` manifest so copied capture folders remain self-identifying.
- App 3.5.1/build 29.

## 3.5.0 / Pi service 0.16.0 / BLE protocol 2.15.0 - 2026-09-11

- Added an in-app lens calibration capture flow: on-demand full-resolution capture with instant per-shot checkerboard-corner feedback, running saved/found totals, and server-side calibration solve (`captureCalibrationImage`, `clearCalibrationImages`, `runLensCalibration`), replacing the earlier blind offline CLI-only workflow.
- Added a lens-calibration sanity check rejecting degenerate solves where fx/fy diverge (a real failure mode found testing with insufficiently varied checkerboard tilt), instead of silently installing a bad calibration.
- Ball tracking now differences each frame against a median of the pre-departure burst (with per-frame flicker normalisation) instead of a global brightness threshold, which merged a white ball into a white tag sheet or lit mat and found nothing. The departure is located anywhere in the burst rather than within +/-8 frames of the coarse presence hint (which proved to be over a hundred frames off in practice), and a resolved 3D track now counts as motion evidence for the capture classification.
- Fixed an infinite false-removal loop: a static scene change (shifted tag sheet, shadow) armed as a ball kept passing the "still present" template check every 0.8 s forever, blocking acquisition. After three identical rejections the detector now disarms (never relearning the background, which bakes a poorly seen real ball in and leaves a ball-shaped hole); a real ball that re-confirms resets that count.
- Ball presence samples are scaled to the learned background's mean brightness before differencing: mains/PWM lamp flicker beating against the sample cadence made the whole lit band read as a scene change, which kept dropping a ball that had just been armed. The detector's largest foreground blob (accepted or rejected, with the reason) is now included in the camera diagnostics and logged, so a marginal ball can be diagnosed rather than guessed at.
- Monitor and Putting screens no longer label an armed state as "Ball detected"; that label now follows actual ball presence.
- Camera hits that resolved ball speed, launch angle and start direction are forwarded to OpenGolfSim (automatically with auto-send, or via a Send button on the capture card), using the same club-based fallback spin complete shots already use; a hit missing any of the three is never sent.
- Sessions now lists every camera hit with the metrics the pipeline actually resolved (ball speed, launch, start direction, or a dash), includes those speeds in the session average, consistency and trend chart, and keeps them out of the complete-shot log rather than padding missing club values.
- Ball presence now uses a brighter-than-background difference rather than an absolute one: the dark hole left where a ball used to be, and shadows, were being armed as balls and produced empty captures.
- The still-present check now probes back through the removal-debounce frames, not only the final frame, so a club moving in to address a ball the detector merely lost sight of no longer fakes a removal. When the ball cannot be seen at all, the detector now checks whether its spot is buried under a large foreground object (a club head resting on it at address) and waits instead of capturing a burst of a stationary ball.
- The app's error for a ball dropped without a capture now says so ("Ball lost before a strike was captured") instead of blaming the camera and storage.
- A busy scene (swing, follow-through, the player's arm) now pauses the removal countdown instead of restarting it, and a lost ball that is not re-confirmed within `PINPOINT_DEPARTURE_TIMEOUT_SECONDS` (default 1.0) forces the removal; previously the departure could scroll out of the frame buffer before the capture fired, producing bursts with no ball in them.
- Start direction no longer depends on how the ground tag is rotated: a calibrated target line (`setTargetLine` from the last resolved ball roll, shown and managed on the Calibration screen) is the reference for start direction and spin axis. Ball speed, launch angle, carry and roll are reported whichever way the tag points; without a target line only start direction stays unavailable, instead of every metric being rejected.
- Ground-tag pose lookup scans outward through the burst instead of trusting one frame (mains lamp flicker and a passing club can hide it), and a stale impact hint no longer snaps to frame 0.
- App 3.5.0/build 28.

## 3.4.0 / Pi service 0.15.0 / BLE protocol 2.14.0 - 2026-09-10

- Added AprilTag-referenced monocular 3D ball estimates, club-tag face-center tracking, smash/contact estimates, surface-feature spin, and observed putting stop/skid estimators.
- Added per-metric estimated/unavailable provenance and reason display; complete core estimates enter the existing shot/putt result contract without synthetic values.
- Retain sensor timestamps and exposure metadata in burst manifests; reject missing timing, calibration mismatch, excessive blur and poor track fits.
- Added lens calibration utility, printable ground/club tags, geometry regressions and measurement setup guide in LAUNCH_MEASUREMENTS.md.
- App 3.4.0/build 27. Hardware deployment and physical accuracy validation remain outstanding.

## 3.3.0 / Pi service 0.14.0 / BLE protocol 2.13.0 - 2026-09-10

- Automatic camera departures now produce capture evidence and uncertainty warnings instead of fabricated shot metrics. Explicit communication-test mode remains synthetic.
- Added automatic annotated image review, adjacent-frame replay, and capture history to Monitor, Putting and Sessions.
- Fixed detector-to-sensor coordinate scaling in false-removal checks and contact-sheet creation for short bursts.
- Added motion-evidence and frame-timing analysis; unavailable physical measurements never enter shot statistics or simulator forwarding.
- Added reconnect retrieval, persisted analysis beside saved bursts, next-ball rearming during result transfer, and visible unsolicited device errors.
- Mobile version 3.3.0, native build 26. See CAPTURE_WORKFLOW.md for remaining limitations and hardware acceptance checks.

## 3.2.2 / Pi service 0.13.2 / BLE protocol 2.12.0 - 2026-09-10

- Changed user-facing speed displays and calculator defaults to km/h while retaining m/s internally for calculations and simulator interoperability.
- Added exact capture IDs to shots and on-demand frame-by-frame 200 FPS replay in the shot summary.
- Recheck the armed-ball image after a suspected departure and reject the shot when the same ball is still present.
- Anchor impact at the first armed-ball loss and retain a 1.2-second grayscale pre-impact history without increasing Pi memory use.
- Report the actual rolling-burst duration instead of the time the ball waited on the tee.
- Updated mobile build versions to 3.2.2/25.

## 3.2.1 / Pi service 0.13.1 / BLE protocol 2.11.0 - 2026-09-10

- Rejected ball-like contours clipped by the detection ROI boundary, preventing the observed edge-lighting false arm.
- Added measured per-frame timestamps and effective FPS to 200 FPS capture manifests for defensible motion calculations.
- Updated mobile build versions to 3.2.1/24.

## 3.2.0 / Pi service 0.13.0 / BLE protocol 2.11.0 - 2026-09-10

- Fixed the 200 FPS rolling buffer so removal debounce and post-impact collection no longer overwrite the actual departure frames; manifests now record the estimated impact frame.
- Added selected-club synchronization over BLE so automatic ball placement/removal captures use the club currently selected in the app.
- Automatically opens a newly completed live shot and returns the app to the Shot screen.
- Updated mobile build versions to 3.2.0/23.

## 3.1.1 - 2026-09-10

- Added the live ball bounding box and explicit detector state to the Calibration camera view, matching the existing Device-screen feedback.
- Updated mobile build versions to 3.1.1/22.

## 3.1.0 / Pi service 0.12.0 / BLE protocol 2.10.0 - 2026-09-10

- Added live AprilTag 36h11 ID 0 detection to the existing CSI/USB camera stream without opening a second camera process.
- Added a BLE calibration capture that persists normalized corners, physical scale, target-line rotation, perspective quality, and an image-to-millimetre homography on the Pi and embeds it into later impact-capture manifests.
- Replaced the Calibration screen placeholder with a live tag outline, detection quality, and real saved calibration results.
- Updated mobile build versions to 3.1.0/21.

## 3.0.0 / Pi service 0.11.0 / BLE protocol 2.9.0 - 2026-09-08

- Replaced the three-second diagnostic buffer with a 200 fps impact burst: 40 pre-impact and 60 post-impact frames.
- Added the Calibration screen's Latest impact frames contact sheet, transferred over BLE for phone review.
- Updated mobile build versions to 3.0.0/20.

## 2.9.0 / Pi service 0.10.0 / BLE protocol 2.8.0 - 2026-09-08

- Added a three-second, 50 fps diagnostic rolling frame buffer. When a confirmed ball leaves the view, LM1 saves the preceding frames and a capture manifest on the Pi; shot metrics remain explicitly synthetic.
- Keeps only the ten most recent diagnostic captures.
- Updated mobile build versions to 2.9.0/19.

## 2.8.0 / Pi service 0.9.0 / BLE protocol 2.7.0 - 2026-09-07

- Added an immediate green app border while LM1 has confirmed ball presence; it clears as soon as the Pi confirms the ball has gone.
- Updated mobile build versions to 2.8.0/18.

## 2.7.0 / Pi service 0.8.0 / BLE protocol 2.6.0 - 2026-09-07

- Added Calibration's Reset empty plane action, which tells the Pi to relearn the clear ball-detection background.
- Updated mobile build versions to 2.7.0/17.

## 2.6.0 - 2026-09-07

- Replaced the bottom-nav Calc tab with a dedicated Calibration tab for portable checkerboard setup.
- Moved the shot calculator into Sessions.
- Added a live checkerboard framing flow with print-size and re-calibration guidance.
- Updated mobile build versions to 2.6.0/16.

## 2.5.0 / Pi service 0.7.0 / BLE protocol 2.5.0 - 2026-09-07

- Stabilized stationary-ball reporting under the 200 fps lighting conditions seen on the live LM1 camera.
- Increased CSI detector sampling from 10 to 50 samples per second while keeping BLE previews at three-second intervals.
- Retained the last confirmed ball box during short contour misses inside the removal debounce window.
- Updated app/build versions to 2.5.0/15 and Pi service/protocol to 0.7.0/2.5.0.

## 2.4.0 / Pi service 0.6.0 / BLE protocol 2.4.0 - 2026-09-07

- Added camera overlay states: calibrating, waiting for ball, ball detected, and detection off.
- Preview metadata contains normalized ball bounds from the same frame; the phone draws the detected-ball box.
- Stale/disconnected previews stop claiming ball detection after ten seconds.
- Enabled ball detection on the existing 640x400, 200 fps CSI setup, sampling every 20 frames for stable placement.
- Suppressed new arming during large scene changes; added calibration, placement/removal, bounds and ROI regression tests.
- App/build updated to 2.4.0/14; Pi service/protocol to 0.6.0/2.4.0. Shot metrics remain synthetic.



## 2.3.0 / Raspberry Pi service 0.5.0 / BLE protocol 2.3.0 — 2026-09-07



- Added Picamera2 CSI capture for the OV9281 on CAM0 at 1280×800 and 30 fps with automatic exposure.

- One camera stream supplies ball detection, BLE placement previews, and full-resolution focus snapshots.

- Added measured exposure/frame duration, camera model, and relative placement-area sharpness to the preview.

- Preserved the CSI image aspect ratio in the app and added manual-focus guidance.

- Added camera timeout cleanup, retry, and stale-camera diagnostics tests.

- Updated app/build versions to 2.3.0/13 and Pi service/protocol to 0.5.0/2.3.0. Shot results remain synthetic.



## 2.2.0 / Raspberry Pi service 0.4.0 / BLE protocol 2.2.0 — 2026-09-04



- Added nearby Wi-Fi scanning, current connection status, hidden SSID entry, and Wi-Fi connection from the LM1 Device screen over the existing BLE link.

- Added NetworkManager-backed `wifiStatus`, `wifiScan`, and `wifiConnect` commands without returning or logging Wi-Fi passwords.

- Added an installer-controlled Wi-Fi provisioning capability and a longer BLE request timeout for network association.

- Made app-to-Pi BLE command chunking byte-safe for non-ASCII SSIDs and passwords.

- Added `install.sh --offline` so an existing Pi service can be upgraded before the Pi has internet access.

- Added Wi-Fi parsing, connection, error-redaction, and protocol regression coverage.

- Updated the app to 2.2.0, iOS build to 12, Android version code to 12, Pi service to 0.4.0, and BLE protocol to 2.2.0.



## 2.1.0 / Raspberry Pi service 0.3.0 / BLE protocol 2.1.0 — 2026-09-04



- Added a low-resolution grayscale camera preview over BLE every three seconds with no Wi-Fi dependency.

- Added a placement-camera card in the LM1 Device screen with the configured detection area and ball target overlaid.

- Bounded preview JPEGs to 2200 bytes and skips a preview if the preceding transfer is still running.

- Updated the app to 2.1.0, iOS build to 11, Android version code to 11, Pi service to 0.3.0, and BLE protocol to 2.1.0.



## Raspberry Pi service 0.2.6 — 2026-09-04



- Hardened automatic arming after live-scene testing exposed false triggers from moving shadows and small texture changes.

- Requires a candidate to remain at a consistent location and size for about two seconds before arming.

- Raised the minimum candidate size and ignores unrelated motion while tracking an armed ball.



## Raspberry Pi service 0.2.5 — 2026-09-04



- Added debounced automatic ball placement and removal detection for the temporary USB webcam.

- A stable ball now arms LM1 PRO automatically; stable removal starts processing and sends the existing explicitly synthetic result.

- Added empty-scene calibration, compact round-object filtering, hand/large-change suppression, automatic camera reconnect, and last-ball-frame capture.

- Added Raspberry Pi OpenCV installation and detector/state-machine regression coverage.



## Raspberry Pi service 0.2.4 — 2026-09-04



- Added optional USB-webcam diagnostic capture to the simulator workflow.

- Detects the actual configured camera device instead of mistaking Raspberry Pi codec nodes for a camera.

- Saves the latest real frame atomically at `/var/lib/pinpoint/usb-test-latest.jpg` while keeping every shot and putting metric explicitly synthetic.

- Added webcam utilities to the repeatable installer and regression coverage for camera status and test capture.



## Raspberry Pi service 0.2.3 — 2026-09-03



- Renamed the Raspberry Pi device and BLE advertising name to `LM1 PRO`.

- Added a safe installer migration from the previous default `Pinpoint LM` names.



## 2.0.2 — 2026-09-03



- Renamed the installed iOS and Android app to `LM1`.

- Changed device connection actions and offline prompts to `Connect to LM1`.

- Updated the app to 2.0.2, iOS build to 10, and Android version code to 10.



## Raspberry Pi service 0.2.2 — 2026-09-03



- Fixed BLE startup with the pinned Bless 0.3.0 permission enum.



## Raspberry Pi service 0.2.1 — 2026-09-03



- Prepared and verified the BLE service package for deployment to the LM1 Raspberry Pi.



## 2.0.1 — 2026-09-03



- Changed the iOS home-screen display name to `LM1 connect`.

- Updated the app to 2.0.1, iOS build to 9, and Android version code to 9.



## 2.0.0 — 2026-09-03



- Replaced Raspberry Pi HTTP/WebSocket communication with a BLE-only GATT protocol.

- Added chunked newline-delimited JSON framing that works with the minimum BLE MTU.

- Added BLE discovery, permissions, reconnect, correlated commands, history, and live notifications to the mobile app.

- Removed the device hostname/IP input and replaced it with nearby Pinpoint discovery.

- Kept Wi-Fi independent and available for OpenGolfSim, internet access, SSH, and updates.

- Replaced the Pi web server and mDNS advertisement with a BlueZ/Bless peripheral service.

- Added Windows-to-Android and Windows-to-EAS iPhone build instructions; Expo Go is no longer used for hardware connections.

- Updated the device protocol to 2.0.0, Pi service to 0.2.0, app to 2.0.0, iOS build to 8, and Android version code to 8.



## 1.5.0 — 2026-09-03



- Added an installable Raspberry Pi HTTP/WebSocket service that starts automatically with systemd.

- Added Avahi/mDNS advertising and a repeatable Raspberry Pi OS installer/updater for `launchmonitor.local`.

- Added camera-free full-shot and putting tests that travel over the real Pi/app connection.

- Added live Pi temperature and disk-space reporting while leaving camera metrics explicitly unavailable.

- Added UI states that distinguish a connected camera-free Pi from a camera capture system.

- Labelled synthetic Pi results so communication checks cannot be mistaken for measurements.

- Added end-to-end tests for status, arming, WebSocket events, shot history, and putting.

- Updated the device contract to 1.4.0 and increased the iOS build number and Android version code to 7.



## 1.4.0 — 2026-09-01



- Added a dedicated Putting tab with putting-mode arming and demo capture.

- Added target-distance and green-speed inputs with decimal-point and decimal-comma support.

- Added measured or estimated roll distance, pace comparison, start line, miss-at-hole, ball speed, putter speed, smash, launch, skid, and strike analysis.

- Added a top-down putt path visualization and recent-putt history.

- Added `/api/v1/putts`, `putt` WebSocket events, and explicit `putting` capture mode to the device contract.

- Added automatic OpenGolfSim forwarding for captured putts.

- Increased the iOS build number and Android version code to 6.



## 1.3.0 — 2026-09-01



- Added OpenGolfSim Desktop and Web connection modes to the Device page.

- Added automatic forwarding for captured and demo shots plus manual calculator sending.

- Added OpenGolfSim device ready/busy status, test shots, player club updates, and shot result summaries.

- Added an Expo Go-compatible WebSocket-to-TCP bridge for OpenGolfSim Desktop port 3111.

- Added measured-spin forwarding with documented club-based fallback spin when the device omits spin.

- Added persisted connection mode, address, email, and automatic-send preference.

- Added an end-to-end bridge integration test and setup guide.

- Increased the iOS build number and Android version code to 5.



## 1.2.0 — 2026-09-01



- Added a dedicated manual shot calculator page and fourth navigation tab.

- Added inputs for club, ball speed, club speed, launch angle, start direction, and strike offsets.

- Added m/s and mph input conversion with decimal-point and decimal-comma support.

- Added calculated smash factor, estimated carry, unit conversions, direction, strike description, trajectory, and clubface results.

- Added realistic input validation and kept manual calculations separate from captured-shot history.

- Increased the iOS build number and Android version code to 4.



## 1.1.0 — 2026-09-01



- Added a persistent club selector for woods, hybrids, irons, and wedges.

- Locked the club selection while the monitor is armed or processing a shot.

- Saved the selected club with live and demo shot results and sent it to the Pi when arming.

- Added estimated carry in metres and yards to the monitor, history, and shot review.

- Added a documented V1 carry fallback based on ball speed, launch, direction, and club profile.

- Increased the iOS build number and Android version code to 3.



## 1.0.1 — 2026-09-01



- Moved the app from Expo SDK 57 to SDK 54 for compatibility with the App Store and Google Play versions of Expo Go.

- Realigned React Native, React, Expo modules, and TypeScript with the SDK 54 dependency matrix.

- Increased the iOS build number and Android version code to 2.



## 1.0.0 — 2026-09-01



- Added the Expo/React Native launch monitor companion app.

- Added live shot, session history, shot review, strike map, and trajectory interfaces.

- Added Raspberry Pi HTTP/WebSocket connectivity with persisted host and automatic retry.

- Added device health, capture controls, calibration status, and interactive demo mode.

- Added the versioned device API contract.
