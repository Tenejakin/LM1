# Changelog

## Pi service 0.62.4 - 2026-10-06

- Strobe now measures slow shots (wedges, short irons). Their flash pattern has one wide gap (1970 us for a 30 m/s ball) so only two flashes fit in a frame, and the copy search needed three in one frame, so it never ran. A new pair fit takes the two copies from each frame and fits all frames together: the same flash repeats every flash period, and the second copy of a frame is either the burst's own flash (one gap later) or the next burst's first (period minus gap later). Both timings are fitted; the straighter line wins, a near tie is ambiguous and not reported.
- A pair result needs at least two frames with exactly two separate copies on one straight line, a speed within 0.6-1.6 times the club's expected speed, a residual under 3 mm and a plausible launch angle. Patterns with three or more flashes use the existing single-frame fit unchanged. A pattern with a single flash per frame is still not measured.
- Replaying the real 22:42 wedge capture (8-bit frames, ball smeared by room light) gives no result: only two frames held two separate blobs and one of them was the club. The fit refuses it, so a pair result needs a dark enough room that the copies come out separate; it has only been verified on synthetic frames so far.
- New messages for a slow pattern: too few frames with a pair (with the count), and the 2-flash case is no longer reported as too short.

## Pi service 0.62.3 - 2026-10-06

- Cut the CPU cost of strobing in the dark. Profiling the idle service with py-spy showed about 28 % of its time in the raw-10-bit-to-8-bit conversion that runs on every frame of both cameras (a float32 subtract, divide, add, clip and cast). It is now two OpenCV passes (a saturating 16-bit subtract, then a scaled saturating narrow) and takes about 0.06 ms per frame instead of 0.9 ms on a PC, with output identical to the old formula for every 16-bit word; other black levels or scales still use the old arithmetic. The Pi was reaching 83 C and throttling, which dropped frames to 80-120 fps.
- A strobe shot whose club pattern fits fewer than 3 flashes per frame (a wedge's single 1970 us gap) is now explained as that, not as the ring not flashing: copies for slow balls need wide gaps and a frame is only about 4 ms long.
- Tests compare the fast conversion with the formula over every 16-bit word.

## Pi service 0.62.2 - 2026-10-06

- Fix a stuck white status LED with no ball detected. In strobe mode the analysis source flipped between the raw 10-bit and 8-bit pictures several times in a few seconds (a single flash-lit frame was enough to leave raw), and every flip restarted the ball detector's empty-plane calibration. With the ball on the mat the new calibration learned it as background, so the detector reported nothing while the Pi still thought a ball was present and kept the LED white.
- The source no longer changes while a ball is on the mat or armed, and leaving raw because the scene brightened now needs 24 steady frames (about 100 ms) instead of one. Turning strobe off still switches at once.
- If a switch does restart the detector while it held a ball, the Pi now reports the ball removed so the app and the LED return to searching.
- Add tests for the flash-lit frame and the ball-on-mat cases.

## Pi service 0.62.1 - 2026-10-06

- Strobe shots that cannot be measured now say why. The old message blamed the long strobe exposure, but the 250 us rule only guards the ordinary frame-by-frame measurement; the flash-copy search does not use it. The new text names what the copy search found: the ring was not flashing when the shot was analysed (with the light controller's mode and error), no copies stood out (or the room light drowned them), copies merged because the ball moved too little between flashes (with the speed that would separate them for the active flash pattern), or copies were found but did not fit the pattern.
- Always save a `diagnostics.strobe` report on strobe captures, including failed ones: light mode, controller state, flash pattern, frames searched, most copies in any frame, copy span in ball widths, and a reason code.
- When a strobe fit measures the shot, the ordinary path's exposure complaint is no longer shown as a failure.
- Add tests for each reason code and the wording. No change to which shots are measured.

## Night strobe prototype 0.8.0 / full shot review 0.1.1 - 2026-10-02

- Replay all ten brighter-setting shots and recover ball tracks of three to five positions. Export projected launch speed and angle, multi-position fit, horizontal/vertical velocity, observed displacement and duration, apparent radius change, and a stationary-to-moving departure bracket where visible.
- Calculate provisional club speed, assumed attack angle and smash factor from available consecutive two-point candidates under the user's level-camera and ball-depth assumptions. Keep feature-identity uncertainty explicit; retain shaft reflection orientation separately from face angle or dynamic loft.
- Flag inconsistent launch fits and substantial apparent size changes. Preserve original raw data and summaries; generate a standalone HTML review and JSON export with track overlays.
- Add extended review output to new single-flash demo captures and the browser page. Review errors do not interrupt raw capture saving. All 29 prototype checks pass, including timestamp units and upward/downward angle signs.

## Night strobe prototype 0.7.1 / club review 0.2.1 - 2026-10-02

- Review all nine 0.7.0 club captures: 120 Hz trigger delivery is stable, but no consistent pre-departure head-centroid track is recovered. Shaft reflections do not supply club speed or attack angle.
- Remove thin vertical shaft pixels before testing the broader head component. Saved-shot replay still rejects the nine shots; do not claim recovered measurements.
- Raise club-mode analogue gain from 1 to 4 while keeping the 250 us flash, 1.5 ms exposure and 3 percent duty unchanged to test head visibility without longer illumination blur.
- All 26 prototype checks pass, including shaft-only rejection and recovery of a synthetic visible head with an attached shaft.

## Night strobe prototype 0.7.0 / club review 0.2.0 - 2026-10-02

- Add club-specific visibility results and rejection reasons to saved captures and the demo display. Replaying existing multi-flash captures does not recover a verified pre-impact head-centre track, so club speed and attack angle remain unavailable for those shots.
- Add an optional single-flash club trial: 120 Hz trigger, one 250 us flash delayed 1 ms, 1.5 ms exposure, and a 242 fps sensor limit. Preserve both camera streams and original timestamps; only the externally triggered view enters the single-flash club speed estimator.
- Fit at least three consecutive, stable-area head candidates to an experimental image-plane speed using ball-depth scale. Reject ambiguous blobs, missing timing, inconsistent paths and post-departure samples. Never call image path direction attack angle.
- Add versioned visibility/replay utilities and four club validity tests. All 24 prototype checks pass, including accepted-copy saving and negative club cases.

## Night strobe prototype 0.6.3 - 2026-10-02

- Fix a crash when saving an accepted three-copy result: preview rendering now supports both the single-frame copy result and the multiple-frame track result.
- Reset status LEDs to searching on demo shutdown so the last processing animation does not persist after an exit.
- All 20 prototype checks pass, including a complete accepted-copy save that creates both the summary and contact preview and returns to searching.

## Night strobe prototype 0.6.2 - 2026-10-02

- After the gentle repeat retained multiple silhouettes and the faster shot had insufficient flight coverage, shorten copy-mode exposure from 19.5 ms to 8 ms and flash gaps from 5/8 ms to 2.5/4 ms. Keep 100 us flashes and 50 Hz bursts at 1.5 percent duty.
- Set the sensor frame-rate limit to 120 in copy mode to reduce the readout period under external triggering. Verify delivered timestamps before requesting another shot; the two views remain independently timed.
- All 17 existing timing, detection and rejection checks pass. Earlier rejected captures and raw images are retained.

## Night strobe prototype 0.6.1 - 2026-10-02

- Resolve touching flash silhouettes with circle voting while retaining the existing coded-spacing ambiguity and residual checks. Preserve rejected images and avoid asserting stereo or calibrated 3D measurements.
- Replay the first dark-room chip: recover three copies in each view, with image-plane estimates of 6.64 m/s at 29.5 degrees and 7.34 m/s at 24.0 degrees. This demonstrates multi-image strobe capture; the trigger pair is still not synchronized.
- Add touching-copy and empty-frame checks; all 17 prototype tests pass. Add versioned contrast review and saved-shot replay utilities.

## Night strobe prototype 0.6.0 - 2026-10-02

- Add optional external triggering of camera 0 in three-copy mode, with a 1 ms flash delay and restoration to free-running capture on shutdown. Camera 1 stays free-running; the pair is not stereo-synchronized.
- Drive searching, ready and processing status LEDs from the standalone demo.
- Add versioned stationary-light diagnostics. Removing camera 0's lens cover restored its IR image; both views locate the ball and the demo arms. Camera 0 delivers roughly 60 ms intervals with 19.5 ms external-trigger exposure while camera 1 delivers 20 ms intervals; this remains a single-view trigger experiment, not a synchronized stereo measurement.

## Status LEDs: ESP32 0.3.0 / Pi service 0.62.0 - 2026-10-01

- Show breathing blue while searching for the ball, steady white when the ball is present, and breathing orange during processing. Processing takes priority over ball presence; status returns to the current ball state afterward.
- Animate both GPIO 7 pixels locally on the ESP32 over a 2.2-second cycle at low brightness. Pi sends only changed states and resends the current state after USB reconnect.
- Add checks for state priority, duplicate-command suppression and reconnect restoration.

## ESP32 strobe controller 0.2.0 - 2026-10-01

- Add two blue status pixels on GPIO 7 at low brightness; the user confirms both LEDs are blue. Build for the current USB-to-UART connection so the Pi can communicate on UART0. Back up the previous 4 MB flash before deployment and verify the flashed firmware.
- Verify camera 0 accepts GPIO 6 external triggers: 48 frames over 2.404 seconds at 20 Hz. Camera 1 produced no frames in external mode during that test. GPIO 5 receives strobe edges, but reported counts and widths require investigation before treating them as a clean exposure window. Restore both cameras to free-running mode afterward.

## Strobe Lab prototype 0.5.3 - 2026-10-01

- Prepare the requested chip experiment at 9 us exposure with the existing three 2 us pulses. Use resting-ball geometry measured in the stationary bench and a low-signal core-brightness departure check, rather than the bright-ball arming threshold intended for longer exposures.
- Median eight frames for the microburst reference to suppress rare flash overlaps. This captures diagnostic shot windows; reliable pulse overlap and moving-shot measurement remain unverified.

## Strobe Lab prototype 0.5.2 - 2026-10-01

- Deploy the requested microburst: three 2 us pulses starting at 0/3/6 us, ending at 8 us, repeated every 4 ms at 0.15% duty. Both cameras remain at 9 us exposure and gain 4.
- Preserve the actual burst in metadata and show it in the demo. This is an unsynchronized illumination experiment, not separated ball copies or verified optical pulse timing.

## Strobe Lab prototype 0.5.1 - 2026-10-01

- Make flash width configurable and deploy the requested 2 us controller pulses with 9 us camera exposure, gain 4 and the existing 250 us flash spacing. Commanded duty is 0.8%; optical pulse shape and camera alignment are not verified.
- Retain actual sensor exposure and controller replies. The 0.5.0 iteration added configurable camera exposure and verified both cameras' minimum actual exposure is 9 us at 640x400.

## Strobe Lab prototype 0.4.0 - 2026-10-01

- Add a three-copy mode: 50 fps, 19.5 ms requested exposure, gain 1, and three 100 us flashes with cyclic start gaps 5/8/7 ms. Electrical duty is 1.5%. Analyze separated copies within each image using all possible flash phases; do not use cross-frame tracking in this mode.
- At 10 m/s, copies are 50/80/70 mm apart and each flash contributes 1 mm motion. Unequal gap ratios distinguish the unknown phase without camera synchronization; exposure boundaries can still truncate a copy.
- Preserve a live off/on raw bench at actual 19497 us exposure. Ambient light already clips part of the placement ROI at minimum gain; measured ROI flash contribution is small. This is an experiment awaiting moving shots, not proof of flash-dominated imaging.
- Use a full-range preview for long exposures. Add a timing test covering all three cyclic phases.

## Strobe Lab prototype 0.3.2 - 2026-10-01

- Log heartbeat failures and the reason for process shutdown. Run the temporary Pi demo with automatic restart after three seconds, addressing repeated unexplained exits that made the browser unavailable.
- Retain the 0.3.1 capture profile and ball locator. All thirteen focused tests pass.

## Strobe Lab prototype 0.3.1 - 2026-10-01

- Locate the resting ball in both camera views before arming, and use its actual position and diameter for trajectory fitting. This fixes the fixed-circle placement mismatch observed during live validation.
- Thirteen focused tests pass on the Pi, including displaced-ball placement. The shortened-exposure profile still awaits new wedge shots.

## Strobe Lab prototype 0.3.0 - 2026-10-01

- Halve the requested exposure to 250 us at 242 fps, with gain 4, to reduce the blur observed in the latest wedge shots. Existing ring timing, 8% electrical duty and hardware wiring are unchanged.
- Detect bright, dark and mixed-contrast ball silhouettes so tracks can continue from the mat onto the bright floor. Prefer the earliest valid interval, reject conflicting overlapping positions, and retain detailed fit rejection reasons.
- Replay preserved 0.2.0 raw captures at their original 497 us exposure: preserve the third shot's upper-camera 10.08 m/s image-plane estimate, recover lower-camera tracks on shots two and three, and continue rejecting shots one and four for excessive blur. Later and earlier image-plane interval estimates are not interchangeable launch-speed measurements.
- Add a versioned replay tool and tests for bright-to-dark transitions and stationary dark-object rejection. Twelve focused tests pass on the Pi; live 250 us shot validation remains pending.

## Strobe Lab prototype 0.2.0 - 2026-10-01

- Review and preserve the first three actual wedge shots plus one placing-hand trigger. Both camera windows captured departure, but the 8 ms images did not resolve separate flash copies; no measurement was emitted.
- Switch the next experiment to 242 fps, 500 us exposure and gain 2, with twenty-microsecond flashes every 250 us (8% electrical duty) on the existing ESP32. IR now illuminates short exposures; motion is timed by sensor timestamps rather than flash-copy separation.
- Add conservative round-ball trajectory fitting across at least three consecutive frames, size/blur/origin/residual checks and rejection of competing trajectories. Outputs remain image-plane estimates and the old long-exposure captures are not reclassified.
- Add a hands-clear arming check and normalized shape comparison so illumination changes do not alone fake departure. Enlarge the raw ring to cover the faster capture window and retain post-trigger frames in contact sheets. Ten focused tests pass on the Pi; the revised profile awaits moving-shot validation.

## Strobe Lab prototype 0.1.1 - 2026-10-01

- Add an isolated, deployed Pi/ESP32 demo in `hardware/strobe-demo/`, with a browser page, dual raw capture, independent sensor timestamps, automatic ball-departure retention and contact sheets. Existing hardware wiring, firmware, app and service versions are unchanged.
- Use gain 1, 120 fps and three 100 us IR flashes spaced 1500 / 2200 us apart for the first wedge experiment. Retain the exact commanded pattern and actual camera metadata with every attempt.
- Fit all cyclic pulse phases without using assumed club speed to choose a result. Reject ambiguous copy sequences; any resolved speed/angle remains an image-plane estimate. No synchronized stereo, direction, spin or carry claim.
- Require ball-to-surroundings contrast before arming; retain unsuccessful attempts for iteration. Five focused timing/arming tests pass on the Pi. Live static capture validates frame saving and rejection of a stationary ball, with both streams sustaining approximately 120 fps. Moving-ball validation awaits user shots.

## Pi service 0.61.1 - 2026-10-01

- Auto-set judges the picture by the ball, not the frame average. The ball is under 1 % of the pixels, so on a dark mat the average is tiny even when the ball is bright, and the old search drove the gain to 16 for every club. Measured on the Pi at the driver's 58 μs shutter: gain 4 gives ball 97 on a noise-free black background; gain 16 gives ball 211 on a background at 26 with noise 32 (and at 100 μs gain 16 the ball is 66 % saturated). The sweep now measures the brightest compact region (the 99.5th percentile of the frame) and aims for the target level; for an evenly lit frame this equals the mean, so such scenes are unchanged. When it has to raise the gain it keeps going until the level is near the target (a ball just over the minimum is fragile), later steps over-correct because the picture's brightness grows more slowly than the gain, an overshoot is brought back down, and the result carries `ballLevel` next to `meanBrightness`.

## Pi service 0.61.0 - 2026-10-01

Review of all 99 retained captures (every shot on the Pi), and the changes it justifies.

- What the captures show. 81 shots were taken at 250 μs or less and 31 of them (38 %) were measured; the other 50 failed with "fewer than three usable 3D ball outlines", and the success rate follows the ball's size in the image exactly as the notes say: 28 % with a 15-20 px ball, 42 % at 26-36 px, 69 % at 39-47 px. The other 18 rejections are the hard 250 μs exposure gate, all of them strobe-mode shots (3.9 ms) in a lit room, where the ring's flashes are lost in the room light and every shot is thrown away by design. The camera is now much closer (the ball is 44-54 px wide), which is the good range; the day's shots simply were not taken in a measuring mode.
- Fix: the saved raw frames missed the impact. A plain "last 100 frames" raw ring had already discarded everything before the hit by the time the departure was confirmed (about 100 frames later), so every raw capture started 20 frames after the impact. The raw ring is now pinned the moment the ball first looks gone: it keeps the frames from just before that and the next 60, then stops adding raw frames, so memory stays bounded (at most 160 raw frames per camera, usually about 90) and the saved window really covers 25 frames before to 45 after the impact. A false alarm releases the pin.
- Auto-set now respects the blur limit for the selected club. The measurement rejects a ball that smears more than 4 mm in one exposure, so the longest usable shutter is 4 mm divided by the ball's speed (driver 58 μs, 7-iron 85 μs, pitching wedge 102 μs, putting unrestricted); the sweep used to look only at brightness and could settle on a shutter the measurement would then reject. It now stays under that limit and buys brightness with gain, and says so when that is still too dark ("Still dark at the 58 us shutter this club needs...", with `blurLimitUs` in the result).
- Plain-language rejection reasons (new `rejection_hints.py`). The cryptic messages now lead with the cause and the fix: a strobe-mode shot in a lit room says the flashes are lost in the room light and to switch Light to Auto, Flat or Daylight; a long shutter outside strobe says how much a 10 m/s chip smears in it and to run Auto-set; too few outlines says how wide the ball is and, if it is under 35 px, to move the camera closer. The original text is kept in the message and in `diagnostics.rejection.original`. Nothing changes about which shots are measured.
- Tried and rejected: a fallback that estimates speed and angle from the presence tracker's own positions. Validated against the 31 strictly measured shots it found a path in only 13 and a reliable one in 4, and gave a reliable estimate for only 3 of the 68 unmeasured shots, because the saved track follows the resting ball and at most one to three moving points. Not shipped.

## Pi service 0.60.0 - 2026-10-01

- The ball detector can run on frames built from the raw 10-bit data (new `raw_frames.py`). Corrected first: raw words are the 10-bit count x 64 (they step by 64), not x 16, and libcamera's black level of 4096 is what the image processor subtracts, not where the data starts (the sensor has already removed its pedestal; the data floor is about 1024 words). `PINPOINT_RAW_BLACK_LEVEL` overrides it.
- Raw is not simply better, and this is deliberate. Measured on the Pi with a ball far above the 64-count crush, the 8-bit picture had the higher signal-to-noise (ball 79 against a black, noise-free background at 60 μs, SNR 158, versus SNR 11 for a raw-derived frame at 1 count per level) because the processor's black crush works as a free noise gate; raw only wins when the signal is under about 64 counts. So in the default `auto` setting (`PINPOINT_ANALYSIS_SOURCE`) the detector and rolling buffer get raw-derived frames only while the ring is strobing AND the scene is dark enough not to saturate (99.5th percentile under 120 counts to enter, over 200 to leave, 12 steady frames to enter, only the primary camera decides); otherwise they get the 8-bit picture exactly as before, so normal shooting is unchanged. When the source switches the detector restarts its calibration, because an empty-plane reference learned from one kind of frame is wrong for the other. `raw` forces raw, `isp` never uses it; `PINPOINT_RAW_COUNTS_PER_LEVEL` sets the mapping (default 1).

## Pi service 0.59.0 - 2026-10-01

- Raw 10-bit capture (`PINPOINT_CAMERA_RAW=true`). The sensor reads 10 bits, but the image processor squeezes them into an 8-bit picture: it subtracts 64 counts (a black level of 4096 words that the sensor has in fact already removed) and then applies a gamma curve of about 0.45, so anything under 64 counts comes out as exactly 0. At a 20 to 100 μs exposure 99.8 to 100 % of the 8-bit picture was 0 while the raw data held a clear signal. Each frame now also carries its linear raw data: the 10-bit count x 64 in a 16-bit word (words step by 64, full scale 65472), with the data floor at about 1024 words. It is 0.5 MB a frame, less than the 0.77 MB 3-channel 8-bit image, and sustained 242.0 fps with no dropped frames on the Pi in testing.
- The Pi has 1 GB of RAM, so only the last 100 raw frames per camera are kept (`PINPOINT_RAW_BUFFER_FRAMES`, about 100 MB for both cameras) and only the frames from 25 before to 45 after the impact are written to the capture folder, as 16-bit `raw-NNNN.png` files with a `raw` entry in `capture.json` (scale 64, black level 1024) (`PINPOINT_RAW_SAVE_BEFORE` / `_AFTER`). Off by default; nothing changes without the setting.
- The strobe copy analysis now works in raw counts when raw frames are present: copies 30 counts above the background (invisible in the 8-bit picture, where they come out as 0) are found, with a lower detection threshold. Without raw frames it falls back to the 8-bit frames as before. The result reports which source it used.
- The existing ball tracking and launch measurement still use the 8-bit picture.

## Pi service 0.58.0 - 2026-10-01

- Ball speed and launch angle from the flash copies of the ball in one strobed frame (new `strobe_copies.py`). In strobe mode, after a shot the analysis looks at the frames just after the ball leaves, picks out the round, ball-sized bright discs (after removing the empty scene), works out which flash made each one from the known uneven gaps (every possible start in the repeating flash sequence is tried and the straightest fit wins) and turns the slope of position against flash time into speed, scaled by the ball's known diameter. It runs only while the light controller reports strobe, uses the exact pattern and rate the ESP32 was given, and reports `ballSpeedMps` and `launchAngleDeg` only when the fit is reliable (at least four copies in a straight row, or three that also match the club's expected speed; residual under 3 mm; a launch angle between -10 and 80 degrees; not ambiguous between two starting flashes). On the 11 real lit-room captures from 2026-10-01 it adds nothing, as it should; otherwise nothing is added and the shot looks as before. The values are marked as estimates: image-plane, side-on, scale from the resting ball. A failure in this step is logged and never breaks the analysis.
- Developed and tested against synthetic frames only (17 tests: speed within 3-4 % for every club family, every start flash, noise, background removal, a wrong pattern flagged as unreliable). It still needs real dark-room captures to tune the thresholds. Light status now also carries `rateHz`.

## Pi service 0.57.1 - 2026-10-01

- Strobe flash pattern now follows the selected club, not just its group. Each club's expected ball speed (club speed times smash) sets the gaps between flashes and the pulse width: gaps keep neighbouring ball copies from overlapping even when the ball is 20 % slower than expected (1.1 ball widths apart) and grow 8 % each so every copy can be told apart; the pulse blurs the ball by about 1.2 mm, so fast balls get short pulses (driver 19 μs) and slow balls longer ones with more light (sand wedge 40 μs). Driver: 4 flashes about 0.95 to 1.1 ms apart; 7-iron: 2 flashes 1.4 ms apart; lob wedge: one flash per frame, because two flashes cannot stay clear of each other inside one 4.1 ms frame at that speed. Status `light.pattern` carries `pulseUs`, `gapsUs` and `ballSpeedMps`; `light.preset` still names the club group, so existing apps are unaffected.

## App 3.44.0 / Pi service 0.57.0 / protocol 2.40.0 - 2026-10-01

- Light modes for indoors, outdoors and dark rooms. The Device screen's Strobe switch becomes a Light selector: Auto, Daylight, Flat and Strobe. Daylight turns the IR ring off and lets the sun light the ball with a short shutter (30 μs by default); Flat keeps the ring steady, as before; Strobe flashes the ring for a dark room. Each light remembers its own shutter and brightness boost, so moving between a sunny garden and a room never costs the settings tuned for the other.
- Auto-set for this room now also picks the light. With the ring off it runs the usual exposure sweep; a usable picture at 100 μs or less means daylight and the ring stays off (it also saves the battery), otherwise the ring goes steady and the sweep repeats. The result says which light was chosen.
- New `light_controller.py` talks to the ESP32 on the ring over USB (`PINPOINT_LIGHT_CONTROL=esp32`). Nothing changes unless that is set. It keeps a heartbeat, reconnects after the cable is replugged and re-applies the wanted mode. In strobe the flash pattern follows the selected club: driver and woods, irons, or wedges and chips.
- ESP32 firmware (hardware/strobe-test/strobe_master): modes `off`, `flat` and `strobe`, a `chip` preset, and a watchdog that returns the ring to steady light if the service stops talking to it for 3 s. It boots in flat light.
- Strobe captures are still saved for review only; launch measurement needs an exposure of 250 μs or less.

## App 3.43.0 / Pi service 0.56.0 / protocol 2.39.0 - 2026-10-01

- Add a strobe test mode for the flashing IR ring (hardware/strobe-test). The Device screen has a Strobe mode switch above Shutter speed. Turning it on remembers the normal shutter speed and sets a 3900 μs exposure, just under one 242 fps frame, so the ESP32's flash bursts land inside the exposure and one picture holds several copies of a moving ball. The shutter limit rises from 250 to 4000 μs only while the mode is on, and turning it off restores the remembered shutter speed.
- New BLE command `setStrobeMode`; `exposureControl` gains `strobeMode`, and the app hides the switch when a service does not report it. Automatic exposure is refused in strobe mode.
- Strobe-mode captures are saved for review only: launch measurement still needs an exposure of 250 μs or less, so they carry a warning and no measurements. Shoot or roll a ball in a dark room with the ESP32 strobe running, then look at the saved frames in History.
- The exposure field now takes four digits.

## Pi service 0.55.3 - 2026-09-29

- Find fast hits that pairing cannot. A ball hit at 17 to 28 m/s is in view for two or three frames, and a blurred or dark one is not found as a clean circle in every frame of either camera, so matching a circle in the lower camera to a circle in the upper one frame by frame found nothing. When that fails the Pi now runs a flight search: it takes everything ball-sized that appears after the hit, in either camera at any frame (a circle where there is one, otherwise a patch that differs from the scene just before the hit, whether the ball is bright on the mat or dark against the window), tries about 100,000 launches from the known resting ball (3 to 80 m/s, launch angle, direction, contact time), keeps the best, centres each sighting and refines. It rejects the answer if a different launch still fits about as well after refinement, if one camera supplies all the sightings, or if the residual stays over 3.5 px.
- Results from the search are accepted with looser image and ray limits (3.5 px, 6 mm) and always stay estimates with a warning saying the ball was found by the search. On the 38 newest saved captures it recovered 5 real hits at 17 to 28 m/s that were discarded, lost none, changed no measured shot, and every hand, foot, nudge and dark false trigger stayed rejected. Against shots measured another way it agrees within about 3 percent in speed, 1 degree in launch and 3 degrees in direction.
- Not recovered: a 31 m/s hit whose sightings disagreed by 10 mm in the ray check.

## Pi service 0.55.2 - 2026-09-29

- Recover real hits the ball tracker loses. When the single-camera tracker fails, the two cameras search for the ball on their own, but that search looked for the resting ball only in the first half of the burst. These bursts hold a long address (the hit falls around frame 100 of 182), so the search never reached the hit and reported no candidates at all. It now scans the whole burst. Replayed over the 32 newest saved captures, 29 were unchanged, 2 were recovered and none changed or was lost; one recovered shot is from 09-26 whose live result was 9.46 m/s at 34.8 degrees and now reads 9.5 at 34.7.
- A single-camera track slower than 0.3 m/s no longer vetoes that search. After a fast hit the tracker sometimes follows a static object (a shadow, the shaft, a foot) for dozens of frames at about 0 m/s, and the two-camera search deferred to it. It now starts fresh from the resting ball instead.
- Still lost: balls so large (65 px across) that they leave the view in about a frame and a half, and balls under 40 px.

## Pi service 0.55.1 - 2026-09-29

- Ball size is now a red "Fix before you hit" with the distance to move. Across every saved capture since 2026-09-25 the ball's size in the lower image decides most outcomes: 40 to 56 px across was measured 44 times in 53, under 40 px once in 14 and over 56 px 3 times in 10. Twelve shots this morning lost four real hits to it (balls 31, 61, 60 and 65 px across); a big ball crosses the view in about three frames, then the tracker either finds nothing or follows a static object. The placement check was an orange warning without a distance; it is now a failure that says how far to move from the ball's size and the lens ("about 12 cm further from the cameras"), and the lower limit rose from 32 to 40 px.
- Not fixed: an address with the club touching the ball can still read as the ball leaving, and a ball hit dark against the bright window on the right is lost. Both are lower-camera tracking limits that staggering does not touch.

## App 3.42.0 / Pi service 0.55.0 / protocol 2.38.0 - 2026-09-29 (branch staggered-cameras, experimental)

Staggered cameras: the upper camera runs half a frame behind the lower one, so together they sample the ball every 2.07 ms instead of every 4.13 ms. Off by default; set `PINPOINT_CAMERA_STAGGER=true` in `/etc/default/pinpoint` to try it.

- Capture. With the flag on, the two sensors free-run with no libcamera sync. At start the upper camera is restarted until its phase behind the lower one is within 0.35 to 0.65 of a frame (about 3 to 7 tries), then held; measured on the Pi it stayed within 20 microseconds over a minute and drifted under 1 microsecond per second. Each pair is an A frame with the B frame half a frame later, and every pair's phase is watched. If the lock cannot be made the cameras fall back to the in-step pair and the app says so.
- Drift handling. Phase within 0.3 to 0.7 is locked. Between 0.2 and 0.3 (or 0.7 and 0.8) the Pi re-locks at the next moment the mat is empty. Beyond that, ball detection is paused and the app shows "Cameras out of step" until the mat is clear and the re-lock finishes, a few seconds. A failed re-lock is retried every 30 seconds while the mat is clear. The upper camera is only ever restarted with no ball present.
- Analysis. `stereo_check` recognises a staggered burst from the frame times, finds the ball in each upper frame from the lower camera's track interpolated to that frame's own instant, and fits with every detection at its own timestamp. Two staggered pairs are four sample instants and are now enough for a full fit (in step they give only a speed estimate). On noisy synthetic frames at 54 to 66 m/s the in-step mode found nothing and the staggered mode fitted 6 to 7 of 12 shots with about 1 percent speed, 0.2 degree launch and 0.5 degree direction error; at 48 m/s it went from 6 to 12 of 12. Where the ball stays in view for many frames it is no better than in step. Club stereo and stereo calibration need simultaneous views, so club stereo is skipped on staggered bursts and calibration refuses to run in staggered mode.
- Saved bursts record `dualCamera.mode: "stagger"` with the nominal offset. Nothing changes with the flag off.
- Not yet tested on the device with a real swing; see scripts/test-stagger-phase.py and scripts/simulate-stagger.py.

## Pi service 0.54.1 - 2026-09-29

- Reword the resting-ball error from the top camera. It told you to recalibrate with the AprilTag, which is no longer used. The usual cause is a ball touching a foot or hand: the lower camera outlines the two as one blob and the top camera cannot find the ball where that box puts it. It now says so, and still mentions a moved camera or stand. Seen on 2026-09-29 with a ball beside a bare toe (ball box 39 x 73 px).

## App 3.41.0 / Pi service 0.54.0 / protocol 2.37.0 - 2026-09-28

Works wherever the stand is put down: no AprilTag needed.

- Take the ground from the stand instead of a tag. The stand is assumed level on the surface the ball is hit from: gravity runs down the rig at the lower camera's pitch, the target is to the right of where the bottom camera points, and the camera height is a stand constant. Each shot corrects that height from the resting ball (up to 40 mm; it was 25 mm from the tag), and shots whose height the two cameras cannot confirm are flagged. Nothing looks for the tag any more; `PINPOINT_GROUND_MODE=tag` restores the old behaviour.
- Add `rig.json`: the stand's pitch, sideways lean and height, written once. `install.sh` derives it from the saved tag calibrations of both cameras, fusing the two tag views through the stereo pair so a noisy single-tag tilt is averaged with a second view and held consistent with the checkerboard geometry. `python rig_pose.py --from-tags|--set PITCH HEIGHT|--show` manages it. A lean inside the tag noise floor (1 degree) is taken as level.
- Replayed on the Pi's 28 newest real shots with identical frames and stereo pair, the rig agrees with the tag pose: ball speed within 0.006 m/s, launch angle within 0.26 degrees and start direction within 0.23 degrees, with two-camera tracking accepted in the same 25 shots. Attack angle moves 0.26 degrees because the tag's 0.26 degree sideways lean is now taken as level. Tilted by half a degree, launch moves about 0.4 degrees per half degree of sideways lean and start direction about 0.2 degrees per half degree of pitch, as the geometry predicts.
- The single-camera fallback (used when the two-camera fit fails) is much more sensitive: on two saved shots half a degree of pitch turned a 32 degree launch into a ground roll. Treat those results as estimates.
- Add a Ground readiness item for the rig ("Level rig, no tag needed" with the constants, or a warning when only default constants exist) and status `rig`. The Calibration screen shows the rig constants instead of asking for the tag. Shot coverage uses the rig pose.
- Add `scripts/compare-ground-modes.py`, which replays saved captures with the tag pose and the rig and reports the differences and the height correction the ball asked for.
- Keep in mind: the level assumption cannot be checked per shot. A stand on a sloped mat or with one foot propped is read as level; a lean along the target line shifts launch angle about one for one, and pitch error shifts direction by about its size times the tangent of the launch angle.

## App 3.40.0 - 2026-09-28

Side-by-side testing against another launch monitor (first target: a Foresight GC3), and sessions to keep the tests organised.

- Add sessions. Start one from the Sessions tab (or the banner on the Monitor screen) and every shot is filed under it until you end it; a session can be resumed, renamed, given notes and a reference-monitor name, and deleted (its shots stay in history). Sessions are kept on the device and in the signed-in account. The Sessions screen has a session picker, and every average, club table and chart follows the picked session. A shot can be moved between sessions from its detail screen.
- Add reference data entry. Each shot's detail screen has a Reference launch monitor card: type in what the other monitor showed for the same swing (ball speed, club speed, launch angle and direction, backspin, spin axis, attack angle, club path, carry, total, apex) in your display units, with Left/Right toggles instead of signs. Everything is optional; entries are validated (ranges, ball speed against club speed, total against carry) and stored with the shot in SI units.
- Add comparison. The shot card shows LM1, the reference and the difference per metric. The session view shows bias, scatter (standard deviation of the difference) and mean absolute error per metric, overall and per named club, so a club with a consistent offset stands out. Excluded shots are left out. LM1 values that are model estimates (carry, total, apex, spin) are labelled, and LM1 club speed, smash, attack angle and club path count only when the camera resolved them.
- Add CSV export of the picked session (Share sheet on the phone, clipboard on web): one row per shot with LM1 and reference columns side by side in display units, LM1 spin source and capture id.
- The comparison ignores the spin axis of 0 the app stores when the camera saw none, and flips the Pi's axis (positive = draw) to the reference convention (positive = fade).
- A capture re-sent for a shot already held no longer discards its session, reference data or excluded flag, and keeps its shot number.
- No measurement changed and the Pi is untouched: service 0.53.0 / protocol 2.36.0.

## Pi service 0.53.0 / protocol 2.36.0 - 2026-09-25

- Take the ground under each shot from the resting ball: both cameras triangulate the 42.67 mm ball on still frames before the swing (the cleanest of three), and the world is shifted so the surface under it is the ground for every fit. Offsets up to 25 mm are corrected; larger ones mean the views matched different things. The stereo resting-height gate is now that 25 mm gross check. On nine chips rejected or estimated at +9..12 mm, the ball measured -2.5..+2.2 mm and three more received two-camera ball values; the +9..12 mm came largely from the stereo fit's own rest-point method, not the surface.
- Placement guidance in the setup check, using the ball as the ruler: from its size in pixels (mm per pixel at the ball) and the room behind, ahead and above it, predict club and ball frames at the player's last five measured speeds (or a typical full swing) and say which way to move the ball. Calibrated on 16 real chips: the head's visible path is ~1.4x the room behind the ball, the first two frames after contact are unusable, and 5+ predicted frames gave club data every time. Balls under 32 px or over 56 px across are flagged.
- The setup check no longer fails a ball that sits a few mm off the calibrated ground; only camera disagreement or a gross offset fails it.

## App 3.39.0 / Pi service 0.52.0 / protocol 2.35.0 - 2026-09-25

- Swing loop above ball speed on the Monitor card and in shot details: the captured swing from 10 frames before the ball moves to 9 after, looping in slow motion. Tap to stop on a frame, step with the arrows or tap the bar to jump (impact marked); tap again to resume. Frames come from the new `captureClip` command: a fixed crop around ball, club and early flight at 240 px, display-brightened, about 1.5-2.5 KB per frame, fetched once per capture in batches of 8.
- Ignore persistent changes when finding the club: a white shoe that shifted slightly differed from the background in every frame and both club trackers followed it at 0.0 m/s.
- Count any club seen near the ball as swing evidence: a topped chip with the club in all 10 frames before impact was classified as a roll with no club.
- Stereo resting-ball height limit 8 mm (was 5): six balls on one soft mat read +1.4..+7.1 mm; stand or tag errors (-16..-20 mm) are still caught.

## Pi service 0.51.0 - 2026-09-25

- Stereo start check allows for contact timing. Contact happens anywhere between the last still and first moving frames (4.1 ms), so the fitted start can sit up to speed x 4.1 ms back along the flight (45 mm at 10.9 m/s); the old plain distance to the resting ball failed good shots against its 30 mm limit. The check now measures the distance to the nearest start any contact time in that window could produce, and reports the implied contact time. On ten recent shots offsets of 17-29 mm became 1-3 mm, with contact 1.3-3.1 ms after the last still frame.
- Club tracking tries both points (hosel, head) with and without the frame just before the ball moves, and uses the best-ranked track that passes the attack-angle, smash and speed checks. Club data on the last ten shots: 5 (was 3); the morning's 15 chips unchanged at 13.
- Save 64 frames after impact (was 48) so saved captures can be replayed through the stereo ball check.

## Pi service 0.50.0 - 2026-09-25

- Track the club head as well as the shaft/hosel point. A visible chrome head broke the hosel point: its lowest point lies on the rounded sole, seen at different spots by the two cameras (13-20 mm ray gaps), and over the light floor the head is darker than the background, so the brighter-only mask kept just the shaft. The head is found by change in either direction in a ground-level window behind the ball, and the point giving the longer consistent track is used. Replay: morning dark-wedge chips 13 of 15 with club data (one recovered by the head point); today's chrome-head chips still 1 of 5, limited by the head being in full view for only 2-4 frames with the ball 18% from the image edge.
- Reject club tracks with an attack angle outside -25..+15° or smash outside 0.7-1.55, for both camera paths. A single-camera track had reported a -34° attack angle on a chip.

## Pi service 0.49.1 - 2026-09-25

- Add `PINPOINT_GROUND_TAG_THICKNESS_MM`: the height of the ground tag's printed face above the hitting surface. With the tag on a 4 mm plate every resting ball read about 4 mm low and failed the 5 mm stereo resting-height gate; on five real chips the error moved from -1..-6 mm to -2..+3 mm with 4 mm set. Both cameras' world frames shift together, so triangulation is unchanged. Saved-capture replays apply the same shift.

## App 3.38.0 / Pi service 0.49.0 / protocol 2.34.0 - 2026-09-25

- Add named clubs ("My clubs" in the club picker): a name, the club type the models use, optional loft and the measured face size, with a how-to-measure guide. Clubs are stored on the device and in the signed-in account.
- Send the selected named club with `setClub`/`arm`; the Pi echoes `bagClubId`/`bagClubName` on each capture so a shot is credited to the club that was selected on the Pi, and writes its face size as the club profile the strike analysis reads (never replacing a hand-made profile).
- Group session statistics, dispersion and gapping by named club, so two sand wedges keep separate numbers. Shot lists, details and the Monitor card show the club's name.
- Strike location still needs the clubhead to stand out from the mat: replaying 15 real chips with a 78 x 50 mm profile found only the 50-54 mm shaft/hosel highlight, which the face-span check rejects.

## App 3.37.0 / Pi service 0.48.0 - 2026-09-25

- Replace the flight model in both the app and the Pi. Checked against Trackman PGA Tour averages, the old model carried a driver 190 yd instead of 275 with a 13 yd apex; the new spin- and speed-dependent aerodynamics carry driver to wedge within 1-7%, with height and landing angle close. App and Pi produce identical carry.
- Add model estimates from the measured launch: total distance, roll (on an assumed green for short steep landings, fairway otherwise), offline distance on the start line, apex, landing angle and hang time. Shown in shot details and, for total and apex, on the Monitor screen. All are labelled as calculated, never observed.
- Estimate dynamic loft and spin loft from launch and attack angle with a rolling-contact impact model; it reproduces a tour 7-iron's ~21° dynamic loft. When launch sits more than 40° above the attack angle the model has no stable answer (one replayed chip gave 65°), so lofts are shown as unavailable.
- Estimate backspin from club speed, launch and attack angle (fitted to tour spin within 10%) instead of the club average whenever the camera resolved the club; the club average remains the fallback. Carry, the simulator and session stats all use the same spin.
- Add session tools: per-club averages with ± spread, carry/offline dispersion plot, gapping between clubs, and a per-shot "Exclude from session stats" toggle that syncs with the shot.

## App 3.36.0 / Pi service 0.47.0 / protocol 2.33.0 - 2026-09-25

- Measure the club with both cameras. The dark head barely shows on the mat, but the lit shaft and hosel highlight do; their vertex is triangulated in both views like the ball, with no swing-plane assumption. Club speed, attack angle and club path come from its 3D track. Replaying 15 real sand-wedge chips resolved 12, with smash mostly 1.16-1.38 (the single-camera path read 1.35-1.61, about 20% low on club speed).
- Three frames are the minimum for every fitted motion: club (stereo and single camera) and ball trajectory, ball-size check and putt roll. More consistent frames join the least-squares fit; from five frames a constant-acceleration term follows the swing arc so attack angle is the value at impact, not the window average.
- Keep the five-parameter free-start roll at six frames: on three frames it fits any track exactly and returned 0.1 m/s at 84° launch in a regression test.
- Reject a club speed whose smash exceeds 1.55, above any real club.
- Show attack angle and club path on the Monitor screen and in shot details, with the reason when unavailable. `clubPathDeg` is reported only from the two-camera track.

## App 3.35.0 / Pi service 0.46.0 / protocol 2.32.0 - 2026-09-25

Workflow fixes from an audit of 40 real captures, where measured shots were lost or polluted by setup faults that were only reported after the swing.

- Check setup when the ball is placed: camera alignment (top camera offset, ray gap and resting-ball height, using the same limits as the stereo fit), ground calibration, exposure against the selected club's typical ball speed, and the clubface profile needed for strike. The Pi sends a `readiness` event and `status.readiness`; the Monitor and Putting screens show what to fix before hitting. Advisory only; it never blocks a capture.
- Keep shots whose ball was measured when the club was not tracked. Club speed, smash and strike are shown as unavailable with the Pi's reason instead of the shot being discarded.
- Classify full-shot movement that cannot be a strike as `not-a-strike`: under 2 m/s, more than 60° off the target line, or a ground roll with no club. These no longer enter shot history or reach the simulator.
- Stop filling club speed, smash and strike from the club profile in the app. Missing values are null with a reason; older saved shots marked as club estimates display the same way.
- Accept a tag-free club track of three clean frames (was four). On the stand the head is in view for 4-5 frames, of which the first is clipped by the image edge and the last merges with the ball; replaying 15 real chips recovered club speed on 13 instead of 7.
- Reject a tag-free club speed whose smash exceeds 1.7, which no real club produces.

## App 3.34.0 - 2026-09-25

- Save the connected Raspberry Pi camera, capture, calibration, placement, and target-line settings to the signed-in user's Supabase preferences.
- Refresh preference timestamps when an existing preference is updated.

## App 3.33.0 / Pi service 0.45.0 / protocol 2.31.0 - 2026-09-25

- Allow three clean paired stereo frames to receive measured-grade status when every existing timing, geometry, calibration, uncertainty, and fit-quality check passes.
- Keep the two-frame path as an estimated ball-speed-only fallback.

## App 3.32.0 / Pi service 0.44.0 / protocol 2.30.0 - 2026-09-25

- Register putting captures even when face strike cannot be measured, and sync the putt to the signed-in Supabase account from the capture event if the Pi's putt event is absent.
- Let the user explicitly recover a saved putt from the Pi into their account. Mark airborne captures and avoid showing fabricated roll or pace values.
- Show putt cloud sync errors instead of silently discarding them.
- Keep airborne putting captures out of automatic simulator sends and avoid duplicate sends when both capture and putt events arrive.

## App 3.31.0 / Pi service 0.43.0 / protocol 2.29.0 - 2026-09-25

- Show the Pi's current capture mode in the shot screen and provide a one-tap switch from Putting to Normal shot, including when putting is already armed.
- Add a direct Normal shot switch on the Putting screen and keep the mode label in sync after reconnecting.
- Block mode changes while a ball is detected so a live capture cannot change type midway.

## App 3.30.0 - 2026-09-25

- Show a camera-pair calibration fit score after validation, with explicit 100-point targets and the original error values.

## Pi service 0.42.0 - 2026-09-24

- Save a shorter full-shot burst after measured departure, while retaining the longer putting capture and keeping both cameras aligned.

## App 3.29.0 - 2026-09-24

- Upload every retained original-resolution camera frame for a shot to private Bunny Storage, with per-user Supabase frame records and resumable Pi uploads.
- Show full-resolution frames in shot review after upload, even when the Pi is disconnected, and show upload progress in shot details.
- Update the Pi service to 0.41.0 / BLE protocol 2.28.0 for direct ticketed frame uploads.

## App 3.28.2 - 2026-09-24

- Preserve Bunny image paths when shot data syncs again, including from older app builds.
- Recover a missing image path from Bunny when restoring account history, or re-upload the capture from a connected Pi when the Bunny image is absent.
- Show shot image upload errors on the Home screen so a failed camera image cannot look like a successful cloud upload.

## App 3.28.1 - 2026-09-24

- Link the LM1 Supabase project, reconcile the existing cloud schema migration, apply shot image columns, and deploy the authenticated `shot-images` Edge Function.
- Configure the Bunny Storage endpoint as a function secret. The storage password still needs to be added in Supabase before image uploads can run.

## App 3.28.0 - 2026-09-24

- Install the Supabase server skill and migrate the shot image Edge Function to `@supabase/server` user authentication with row-level-secured database access.

## App 3.27.0 - 2026-09-24

- Save each signed-in user's live shots and putts to Supabase, upload primary and upper-camera shot images to private Bunny Storage through an authenticated Edge Function, and restore images in shot review.
- Keep pending uploads scoped to the signed-in account and stop importing the shared Pi history into a user's cloud account.

## App 3.26.0 - 2026-09-24

- Refresh Supabase Auth tokens with React Native foreground/background state and retry cloud restores once after a JWT-related failure.

## App 3.25.0 - 2026-09-24

- Update Bunny Storage setup template with the LM1 Frankfurt storage endpoint and clarify that uploads require the write-capable storage password; CDN configuration is optional.

## App 3.24.0 - 2026-09-24

- Document Bunny Storage upload secrets as server-side Supabase Edge Function configuration; keep them out of the Expo client environment.

## App 3.23.0 - 2026-09-24

- Require a restored Supabase session before mounting the LM1 app, device providers, and feature tabs.

## App 3.22.0 - 2026-09-24

- Complete the initial Supabase account lifecycle with signup confirmation messaging, password reset email requests, and visible auth status feedback.

## App 3.21.0 - 2026-09-24

- Add optional Supabase account support, offline upload queues for shots and putts, a cloud account screen, and an initial row-level-secured cloud schema.

## App 3.20.0 / Pi service 0.40.0 / protocol 2.27.0 - 2026-09-24

- Estimate interval-average ball speed from exactly two clean stereo ball matches when their timing, ray geometry, resting-ball path, and one-pixel speed sensitivity pass strict checks.
- Keep two-frame speed explicitly estimated; do not infer launch angle, direction, carry, or a measured-grade trajectory from two positions. Reject weak geometry rather than filling numbers.
- Show two-frame speed provenance and uncertainty in iPhone capture review.

## App 3.19.1 / Pi service 0.39.1 / protocol 2.26.1 - 2026-09-24

- Show when a valid single-camera trajectory was used after stereo matching failed, and report stereo and mono failures separately when neither yields a trustworthy launch measurement.
- Do not label a failed capture as having a single-camera measurement or mark a rejected stereo track as matched.

## App 3.19.0 / Pi service 0.39.0 / protocol 2.26.0 - 2026-09-24

- Restrict automatic ball placement and arming to the lower camera's left half (`x = 0%–50%`, `y = 30%–98%`), leaving the right half for left-to-right launch tracking. A ball crossing the zone boundary is rejected unless its full contour fits inside.
- Move the live-preview target ring to the centre of that zone and explain the upper camera must also keep the ball visible.
- Migrate only the previous stock ROI during offline Pi updates; preserve user-customized zones.

## App 3.18.2 - 2026-09-24

- Show start direction consistently as a magnitude with L/R in shot review, capture review and history.
- Explain the left-to-right rig convention: R/positive means toward the cameras, L/negative means away. Keep the numeric sign unchanged in stored data and simulator messages.

## App 3.18.1 / Pi service 0.38.1 / protocol 2.25.1 - 2026-09-24

- Preserve tag-free silhouette club speed, smash factor and attack angle when no club marker profile is installed; an explicitly mismatched marker profile is still rejected.
- Stack ball speed and carry on phone-sized shot reviews so the carry and measurement summary remain visible.
- Label the assumed backspin used for carry without presenting it as camera-measured spin.

## App 3.18.0 / Pi service 0.38.0 / protocol 2.25.0 - 2026-09-23

- Carry is always a still-air flight-model estimate from launch speed, angle, target-line direction and backspin, never a landing measurement.
- When spin is unavailable, use the selected club's typical spin scaled for shot speed and, when measured, adjusted for attack angle. Surface-spin failure remains visible in the capture review.
- Retire the vacuum carry and club carry-factor calculations. Recalculate legacy app shots with the new model and label the model limits and assumed inputs.
- Expose carry-model spin provenance on the Pi capture, and apply the same fallback to OpenGolfSim.

## App 3.17.0 / Pi service 0.37.0 / protocol 2.24.0 - 2026-09-23

- Added a separate fixed-pair calibration window with both live views, board settings, synchronized capture, held-out validation and explicit activation.
- New `stereo_calibration.py` supports app-driven calibration and offline session solving, fixed lens inputs, symmetric checkerboard ordering, timing/diversity checks, versioned sessions and activation backups.
- Activated pair geometry now supplies the top camera's world pose from the bottom camera's ground pose. Lens/resolution/camera-order mismatches reject stereo instead of reusing stale geometry.
- Shot capture pauses during the calibration window; the lease expires after disconnection. Existing calibration and history are preserved until explicit activation; active pair snapshots accompany new captures.

## App 3.16.1 / Pi service 0.36.1 / protocol 2.23.0 - 2026-09-23

- Zero shot direction always follows the bottom camera's left-to-right axis projected onto the ground. Legacy manual target lines are ignored, not deleted.
- Calibration screen explains automatic direction and removes manual roll controls. AprilTag rotation does not define the target heading.
- Direction grading accepts the explicit camera-relative reference; physical alignment with the intended target remains the user's responsibility.
- Regression tests cover saved-line override prevention and invariance under ground-tag coordinate rotation.

## App 3.16.0 / Pi service 0.36.0 / protocol 2.23.0 - 2026-09-23

- Reject stale target headings after ground recalibration and prevent setting the
  target from a capture made in the previous ground coordinate system.
- Separate club-motion evidence from ball movement. Captures without a resolved
  pre-impact club track stay available for review but do not become full shots
  or reach the simulator. No minimum shot speed is imposed on gentle chips.
- Prefer the joint stereo launch when its geometry checks pass, even if the
  single-camera fit succeeded. Preserve failed stereo checks and clearly name
  the actual measurement source when using the single-camera estimate.
- Recover a resting ball displaced within one diameter of the armed box, using
  a persistent stationary cluster; constrain ground stereo fits to zero vertical
  velocity. Hide club-profile placeholders for unresolved club, spin and strike
  values in the main shot views.
- Add an audit/replay script that uses each saved capture's original calibration
  and shared sensor timestamps, writing separate comparison reports.

## App 3.15.0 / Pi service 0.35.0 / protocol 2.22.0 - 2026-09-23

- Do not create or send a camera shot when speed, launch angle, or direction is
  unavailable. Keep the raw capture visible as failed tracking instead of
  replacing missing ball speed with a club-profile default.
- Preserve paired stereo frame indices and rejection counts on tracking failure.
  Show matched frames and failed speed-quality checks in capture review.
- Stop displaying an uncalibrated quality score as a percentage of accuracy for
  camera shots. Retain measured/estimated labels and individual quality checks.

## Pi service 0.34.0 / protocol 2.21.0 - 2026-09-23

- Retry independent stereo ball-circle detection with a slightly more sensitive
  edge threshold only when the normal pass cannot form a geometric camera pair.
  The recovered pair must still pass size, ray-agreement, and trajectory checks.
- Allow three paired frames spanning at least 8 ms to produce an estimated
  stereo launch. Six paired frames remain required for measured-grade metrics.

## Pi service 0.33.0 / protocol 2.21.0 - 2026-09-23

- Detect ball-sized circles independently in both calibrated camera bursts when
  the single-camera trajectory is missing or unreliable. Pair candidates by
  ray agreement and apparent size, follow a coherent 3D path, and fit speed,
  launch and direction from the paired sensor timestamps.
- Recover the last stationary ball directly from the lower burst when its old
  tracker supplies no track. Refine the upper resting-ball centre with a circle
  fit so a nearby club does not shift the stereo start position.
- Record the frame number and reason for each rejected independent candidate;
  stop searching after the ball has been absent for eight frames.
- On the saved 2026-09-23 shot, this recovers 10 paired frames that the old
  lower-camera tracker skipped. The result remains an estimate pending
  reference-launch-monitor validation.

## Pi service 0.32.0 / protocol 2.21.0 - 2026-09-23

- Use calibrated paired-camera observations for an independent stereo launch
  fit when the single-camera trajectory fit fails, including failures caused by
  unusable ball-outline size estimates.
- Require both cameras' saved lens and ground-tag calibrations, matching frame
  pairs, at least six upper-camera ball matches, close ray agreement, a plausible
  start at the resting ball, and bounded reprojection residual before accepting
  stereo recovery. Missing or poor stereo evidence leaves metrics unavailable.
- Keep stereo as a cross-check when the single-camera fit succeeds. Record both
  pose errors, pair timing, start-anchor error, stereo residual, and the
  two-camera 3D track in capture analysis; BLE metric fields remain compatible.
- This adds a calibrated stereo measurement path; accuracy still requires
  validation against a reference launch monitor.

## App 3.14.0 / Pi service 0.31.0 / protocol 2.21.0 - 2026-09-22

- Lens calibration is now per camera. The Calibration screen has a Lower CAM0 /
  Upper CAM1 selector that switches the checkerboard preview to that camera's
  live view, shows only that camera's saved/corners-found counts, and reports
  whether intrinsics are installed for it.
- `captureCalibrationImage`, `clearCalibrationImages` and `runLensCalibration`
  take `camera` (`primary` or `secondary`, default `primary`). Each camera keeps
  its own folder of views and its own intrinsics file; the second camera writes
  to `PINPOINT_SECONDARY_INTRINSICS_PATH`
  (`/var/lib/pinpoint/intrinsics-secondary.json`). Views saved before this
  release are moved into the primary camera's folder, so its counts carry over.
- Capturing for the upper camera is refused when the second stream is not
  running, instead of silently saving the lower camera's view.
- Only a primary solve clears the saved ground calibration and target line,
  because the measurement geometry is built on that lens. A secondary solve
  leaves them alone.
- Status adds `lensCalibration` (installed intrinsics per camera) and
  `calibrationCapture.cameras` (counts per camera); the existing top-level
  counts still describe the primary camera.
- The second camera's intrinsics are stored only. Stereo calibration, extrinsics
  and 3D measurement from both views remain unavailable; measurements still use
  the lower camera alone.
- Shot coverage at ~240 fps: new `shotCoverage` command and a Shot coverage
  card on the Calibration screen. It projects a putt, wedge, 7-iron and driver
  launch from the detected ball through the saved lens + ground pose, and
  reports travel per frame, visible path and the 2 possible frame counts, rated
  good (>=4), just enough (3) or too few. It also suggests moving the ball
  upstream or the camera back. Geometry only.
- 23 new Pi tests (220 total) pass. TypeScript and lint pass. Not yet run
  against the physical dual-camera Pi.

## App 3.13.0 / Pi service 0.30.0 / protocol 2.20.0 - 2026-09-22

- Dual OV9281 acquisition for vertical enclosure v0.7.2: lower CAM0 triggers
  one burst containing both views. Shared exposure/gain controls, dual live
  previews, and matching upper frames in capture review and replay.
- Software synchronization with independently buffered sensors, timestamp
  pairing within 250 microseconds, and explicit failure when either camera
  or timing lock is unavailable. Intermittent SyncReady metadata is retained.
- Saves upper frames in camera-secondary, with separate timestamps and a contact
  sheet. The main manifest records pair offsets; diagnostics include paired fps.
- Verified profile: 640x400, requested 242 fps, 10-bit mode. Full detector/preview
  run measured 241.56 paired fps and maximum 54 microseconds offset. Faster
  243-245 fps stalled; 280/300 fps in 8-bit mode failed the pairing tolerance.
- Measurement calculations still use the lower camera; stereo geometry and
  physical accuracy need calibration and validation. Existing history works.
- Versioned setup/backup/verification scripts and DUAL_CAMERA_SETUP.md describe
  placement, lighting, measured results and rollback.

## App 3.12.0 / Pi service 0.29.0 / protocol 2.19.0 - 2026-09-18

Values are now labelled measured or estimated from real quality checks, instead of every camera value showing a flat 70%.

- Pi: every reported metric is graded after analysis. It is labelled `measured` only when every quality gate passes: ground-tag pose error, trajectory-fit residual, speed and angle fit uncertainty, spin sample count, club-tag pose count, and a rolled-ball target line for start direction. Otherwise it is `estimated`, with a `confidence` that falls with each failed gate, scaled by how far the value missed. Each metric also lists its `checks`.
- Previously no value was ever labelled measured, so the app gave every camera value 70%, and the overall score was capped at 65% by the fixed strike value.
- Carry, face contact, roll/skid and all tag-free club values are always estimates, because each rests on a model or an assumption. Smash is measured only when both speeds are.
- App: every value on the shot screen shows a Measured or Estimated badge. The percentage appears only on estimates. Tapping a value opens a small window with the quality checks (passed/failed) and the device's explanation of how the value was produced. Club-profile fallbacks explain why the camera could not provide the value.
- Older Pi firmware without grades still works: its values show as estimates at the previous default.
- Measured means "passed this device's own checks". It has not been validated against a reference launch monitor.
- 6 new Pi tests for the grading; all Pi tests pass. TypeScript and lint pass.

Sharper edges for the ball and the ground tag.

- Ground AprilTag corners are now refined to sub-pixel accuracy (`CORNER_REFINE_SUBPIX`). OpenCV's default left them at the whole-pixel quad fit. On replays of the saved captures, the three worst tag poses dropped from 1.45 / 1.25 / 1.55 px to 1.04 / 1.17 / 0.96 px. The other methods were worse or lost the tag on one capture. Override with `PINPOINT_APRILTAG_CORNER_REFINE` (`none`, `subpix`, `contour`, `apriltag`).
- The ball's apparent size now comes from a sub-pixel edge fit instead of the enclosing circle of a thresholded mask:
  - 72 rays run outward from the tracked centre;
  - each edge sits at the half-contrast crossing in the flicker-corrected difference image;
  - RANSAC keeps the largest outline arc that is truly circular, and it must span at least 150°.
  Real balls are side-lit, with a dim limb that fades into the background, and on these captures the top is cut off flat by a shadow line. A plain fit averaged both in. On synthetic balls the fit is within 0.6% of the true radius when evenly lit, and within about 1.2% when side-lit or cut off flat. On real frames each fit's outline residual is about 0.3 px, and the slow putt now has an edge-fitted size in 33 of 42 frames.
- Size is weighted by its measured frame-to-frame jitter (0.65–0.9 px on real captures). The edge fit's centre is *not* used: which lit arc it locks onto shifts between frames, and it raised the track residual from about 1.5 to about 2.1 px against the template-matched centre.
- New scale self-check using the standard 42.67 mm ball: `trajectoryFit.ballSizeRatio` is the measured over the predicted apparent size. Away from 1, the tag size, lens model or ground pose is scaling every distance, and so every speed. It is a grading check (within 5% for "measured"). On replays, the two clean ground-roll shots read 0.96–0.97. The flight shot reporting a 58° launch reads 0.83, so its implausible launch is now flagged.
- Ball compression: a struck ball is flattened and ringing at contact, so the first moving frame's size, and any frame within 3 ms of it, is never used; only its position is.
- Net effect on the saved captures is modest. Speeds moved by 0–4%. Track residual is unchanged at about 1.5 px, because it is dominated by the template centre, not size. Most values stay estimates, mainly because of that residual. `scripts/replay-edge-precision.py` reproduces the comparison; results are in `output/edge-precision/`.
- JPEG replays with no reference launch monitor: tighter and more self-consistent, not proven more accurate.
- 8 new Pi tests (synthetic edge-fit accuracy and the compression window).
- Installer: `install.sh` now also installs `club_vision.py` (needed since 0.27.0, previously copied by hand) and `exposure_calibration.py` (needed since 0.28.0). Without it, an installer-only update to 0.28.0 would have left automatic exposure unable to import.

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
