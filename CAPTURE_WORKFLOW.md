# Camera workflow review — 3.3.0

Historical 3.3.0 review. The subsequent 3.4.0 measurement implementation and current setup are documented in [LAUNCH_MEASUREMENTS.md](./LAUNCH_MEASUREMENTS.md); its metric support supersedes the unavailable-pipeline statements below.

App 3.3.0/build 26; Pi service 0.14.0; BLE protocol 2.13.0.

## What now works in software

Keep the hitting area empty while the camera learns its background. Place a ball fully inside the detection region. Stable presence arms the monitor. A debounced departure retains the rolling burst, checks whether the original ball is still there, then scans the full-rate frames to separate the coarse trigger from the last stationary and first moving ball frames before sending a `capture` record. The Monitor and Putting screens automatically show the annotated contact-window image, observed frame rate, retained duration and limitations. Sessions lists the last ten captures; previous/next buttons retrieve actual frames from that exact burst. The device returns to ready, or armed if a replacement ball arrived during transfer.

Camera capture does not create a synthetic shot or send made-up metrics to OpenGolfSim. Demo/manual connection tests still use synthetic values. Capture evidence is intentionally separate from measured shot statistics.

## Confirmed issues and fixes

| Severity | Finding | Resolution |
| --- | --- | --- |
| High | Ball removal generated club-profile synthetic speed, launch, direction and clubface coordinates. | Camera evidence now uses a separate capture result, with unsupported measurements explicitly unavailable. |
| High | `camera` backend ignored automatic ball events entirely. | Presence now arms both backends; camera evidence is processed independently of simulator selection. |
| High | False-removal template used 640-wide detector bounds against 1280-wide images. | Bounds are scaled into the actual sensor frame before comparison. |
| Medium | Only a modal offered capture imagery; no automatic evidence view. | Added capture image cards to Monitor, Putting and Sessions. |
| Medium | Short contact sheets could concatenate rows with different widths. | Pad incomplete rows; tests cover 1, 3, 5 and 9 frames. |
| Medium | Ball arriving during result delivery could miss rearming. | Remember latest presence and restore armed state after delivery. |
| Medium | Calibration reset could leave an old armed state. | Reset clears protocol presence and state. |
| Medium | Unsolicited device failures disappeared at the client boundary. | Surface them in the app error banner. |
| Medium | Reconnecting while processing tried to change club and failed the connection. | Synchronize club only when ready. |
| Medium | Replay cache hit could leave a spinner visible. | Reset loading/error when using a cached frame. |
| Medium | Camera analysis disappeared after service restart. | Save analysis beside its burst and restore the latest ten; warn if saving fails. |
| Low | Replay claimed 200 FPS regardless of actual capture. | Use a neutral camera label and report observed FPS from frame arrivals. |

## Remaining issues — do not treat this as a calibrated launch monitor yet

1. **Departure is not proof of strike.** A hand lifting the ball, occlusion or moving a ball can trigger a candidate. Template matches can follow similar objects. Motion evidence is labeled as such; it is not a validated strike classifier. A club-contact detector or synchronized impact sensor plus outgoing-ball tracking is still needed.
2. **Physical metrics are not implemented/validated.** Ball speed, club speed, smash, launch angle, start direction, spin, clubface strike coordinates and carry cannot be asserted by this implementation. The app retains its existing metric views for measured external/device shots and demo/manual data. Capture records explicitly list these values as unavailable.
3. **A ground-plane AprilTag does not calibrate airborne 3D motion.** Camera intrinsics, distortion, pose, target-line alignment, and measurement-plane constraints need validation. Spin needs resolvable ball markings/features; clubface coordinates require clubface localization. Do not infer these from club selection.
4. **Exact contact may lie between frames.** At 200 FPS frames are 5 ms apart; a hypothetical 70 m/s ball moves 35 cm in that time. Exposure blur and field of view can prevent any outgoing observation. When motion resolves, the UI shows an interval from the last stationary frame to the first moving frame; otherwise it labels only the coarse disappearance trigger, never exact impact.
5. **Host arrival times are not sensor exposure times.** Observed FPS and gap warnings are diagnostic. Speed needs sensor timestamps, dropped-frame validation and exposure-aware tracking.
6. **Startup needs an empty scene.** A ball already present becomes background. Clear the zone and reset empty-plane calibration, then replace the ball. Lighting changes, shadows, hands, clutter and a ball touching the ROI boundary remain detection hazards. Use fixed exposure/lighting and a clear, contrasting hitting surface.
7. **Camera work still pauses while analyzing/saving a burst.** Full-frame template matching, JPEG writes, previews and AprilTag work share the camera worker. Wait for ready before placing the next ball. Production high-speed capture should decouple acquisition with a bounded worker queue and measure frame losses under load.
8. **Long occlusion can outlast the rolling buffer.** The earliest estimated departure may no longer be retained. A bounded strike-candidate timeout/trigger buffer is needed for robust club/hand occlusion handling.
9. **BLE imagery is intentionally small and slow.** Initial image is compressed to the existing 2.2 KB JPEG budget. Fine ball markings and exact contact cannot be reviewed reliably at this resolution. Full JPEGs remain on the Pi; use those for validation. History retrieval can take tens of seconds.
10. **Retention is ten bursts.** Older Pi frames/analysis are pruned. A failed disk write leaves only the current-session image; captures have no phone-side archival persistence. Export/storage policy is still needed for long-term sessions.
11. **Camera failure recovery needs hardware validation.** Repeated read failures and stream exceptions now emit lost presence to clear an armed capture. A blocked driver or stale BLE preview can still delay that update. Do not swing until live preview and presence are current.
12. **Existing statistics/history can contain earlier synthetic results.** The new capture path keeps its records separate; it does not retroactively turn earlier data into measurements.

## Validation and deployment

Software tests cover image evidence, ambiguous removal, timing gaps, coordinate scaling, short bursts, ready/armed/processing transitions, repeat capture, transfer failure and replacement-ball rearming. Existing protocol, camera, Wi-Fi, calibration and simulator tests also run. TypeScript and lint must pass. Synthetic fixture tests establish software behavior, not physical accuracy.

Verified in this task: 55 Python tests passed with OpenCV enabled; fragmented-BLE capture-client integration passed; OpenGolfSim bridge integration passed; TypeScript and ESLint passed; production web export succeeded at `output/capture-workflow-3.3.0`. Native UI rendering and a real BLE/camera strike were not tested. The workspace already contained substantial uncommitted changes; those were retained.

Install the updated Pi files with the existing `sudo ./raspberry_pi/install.sh` procedure (or `--offline` on an already provisioned Pi). Ensure `/etc/default/pinpoint` has `PINPOINT_AUTO_BALL_DETECTION=true`, with the correct camera source/resolution/exposure. The installer already enables automatic detection. Update/reload the Expo app to 3.3.0; native build identifiers are 26. No new native dependency is required.

Hardware acceptance sequence:

1. Verify fresh preview, actual exposure, focus and clear calibration area; then place a ball and confirm armed.
2. Leave it still, pass a club nearby, lift it by hand and change lighting. No candidate may be presented as a confirmed measured shot.
3. Strike into a safe net and confirm the capture image, timing and warnings appear automatically. Step through the full-resolution saved burst and locate the outgoing ball.
4. Repeat at least ten times, including putting and faster shots; record missed departures, false candidates, dropped frames and save latency.
5. Disconnect during transfer, reconnect and verify capture retrieval. Restart the Pi service and verify retained analysis. Test low disk space and camera loss.
6. Compare any future physical metric pipeline against an independent reference before enabling measured-shot output.

No live Pi deployment, real strike or physical accuracy validation was performed in this task. An existing local contact sheet was inspected, but it does not visibly establish a golf strike.
