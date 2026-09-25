# Dual OV9281 setup — v1.2.0

App 3.14.0 / build 50 · Pi service 0.33.0 · protocol 2.21.0.

## Enclosure and camera roles

This profile follows the latest vertical enclosure v0.7.2. The user confirmed
that **CAM0 is the lower camera**. It detects the ball and triggers both saved
views. CAM1 is the upper camera. The stand's nominal lens heights are 162.5 mm
and 247.5 mm, its vertical baseline is 85 mm, and both cameras point down 18°.
These CAD dimensions are mounting references, not measured stereo calibration.

1. Keep both lenses parallel in the carrier. Aim the whole enclosure so the
   ball and its initial path are visible in both previews.
2. Turn on the hitting-area illumination. Both views were still very dark at
   the saved short shutter setting during the installation checks.
3. Reload app 3.13.0 and connect. Device shows the lower placement preview,
   upper preview, matched frame rate and timing status. Use the existing shutter
   and brightness controls; both cameras receive the same settings. Automatic
   brightness uses the lower view, so also inspect the upper view for clipping.
4. Put a printed target at ball distance and focus each lens manually. The
   existing numeric sharpness score refers to the lower view only.
5. Remove the ball and hands, then reset the empty background after aiming or
   changing lighting. Place a ball in the lower preview's detection region.
   When it departs, both views are saved under one capture ID. The upper view
   accompanies the initial capture image and matching replay frames.

## Calibrating each camera

App 3.14.0 calibrates the lenses one camera at a time. On the Calibration
screen, the lens calibration card has a **Lower CAM0 / Upper CAM1** selector.
The preview under it shows the selected camera's live view, and the counts,
Clear images and Run calibration all act on that camera alone.

1. Select a camera, hold the printed checkerboard in its preview and capture at
   least 12 diverse tilted views. Views are never shared between cameras.
2. Run calibration for that camera, then repeat for the other one. The upper
   camera's intrinsics are written to
   `/var/lib/pinpoint/intrinsics-secondary.json`
   (`PINPOINT_SECONDARY_INTRINSICS_PATH`).
3. Running it for the lower camera clears the saved ground calibration and
   target line, because launch geometry is built on that lens; capture the
   AprilTag again afterwards. A run for the upper camera leaves them untouched.

Upper CAM1 is selectable only while the second stream is running; a capture
request for it is refused otherwise rather than saving the lower view.

The same fixed AprilTag 36h11 ID 0 calibration must be captured in both camera
views after installing each camera's intrinsics. Each stored camera pose uses
the tag's shared coordinate frame; together they define the stereo geometry.
The primary camera remains the shot trigger. When its own trajectory fit
succeeds, the upper image cross-checks the ball along the expected ray path.
When that fit fails, both image bursts independently supply ball-sized circle
candidates. The service pairs them using the calibrated rays, apparent ball
size and a coherent 3D path. Changing either camera, lens focus, tag location
or hitting surface requires recalibrating the affected lens/pose before trusting
stereo results.

## Stereo measurement quality gates

Service 0.33.0 keeps the monocular fit as the first path and runs stereo as a
cross-check. If the monocular fit fails, independent detections from both views
can recover a trajectory even without its lower-view track. A stereo-only
result needs at least three paired detections and passes paired timing (≤250 μs),
median ray gap (≤3 mm),
resting-ball height (≤5 mm), start anchor (≤30 mm), and joint image residual
(≤3 px) checks. Failed gates leave the result unavailable. Review
`measurements.diagnostics.stereo` in `analysis.json` to see matches, rejected
frame numbers and reasons, calibration errors and fit diagnostics. These are still camera-derived
estimates until checked against a reference launch monitor.

## Designing for 240 fps: shot coverage

At 241.6 paired fps there are 4.14 ms between frames. The launch fit needs the
ball in at least 3 frames after impact (4 gives it a residual to check), so the
limit is how much of the ball's early path the camera sees, not the frame rate:

| Shot | Ball speed | Travel per frame | Path for 3 frames |
|---|---|---|---|
| Putt | 3 m/s | 1.2 cm | 4 cm |
| Wedge | 30 m/s | 12 cm | 37 cm |
| 7-iron | 54 m/s | 22 cm | 67 cm |
| Driver | 70 m/s | 29 cm | 87 cm |

Projected through the lens and ground pose saved with capture
`capture-1789515451301879262` (the lower camera about 34 cm from the ball, as
set up before the v0.7.2 stand), then with that camera pulled back along the
same aim:

| Camera to ball | Ball placement | Ball width | 7-iron frames | Driver frames |
|---|---|---|---|---|
| 34 cm (as saved) | mid-frame | 70 px | 0 | 0 |
| 34 cm | upstream edge | 72 px | 1 | 1 |
| 67 cm | upstream edge | 37 px | 3 | 2 |
| 99 cm | mid-frame | 24 px | 2 | 1 |
| 97 cm | upstream edge | 25 px | 5 | 4 |
| 129 cm | upstream edge | 19 px | 6 | 5 |

Frame counts are the minimum of the two possible values. "Upstream edge" means
as close to the image edge as the whole ball still fits; at about 1 m, placing
the ball 10% in from the edge drops the driver to 3 frames. Rolled putts get
dozens of frames in every case.

Conclusions:

1. 240 fps is enough for ball speed, launch and direction if the lower camera is
   about **1 m from the ball** and the ball sits near the **upstream edge** of
   the image. Half of a centred view is wasted behind the ball.
2. The ball is then about 25 px wide. That is fine for centroid tracking and
   depth from ball size, but too small for spin from surface marks. Spin stays
   estimated unless strobed multi-exposure is added later.
3. Check your own setup with **Calibration → Shot coverage** after saving the
   lens and AprilTag calibration, with a ball placed where you hit from. It
   uses the live ball position and the measured paired frame rate.

The v0.7.2 stand has no saved ground pose yet, so its coverage has not been
calculated. The table above describes the older lower-camera geometry.

## Capture settings and timing

- Two OV9281 streams at **640×400, requested 242 fps, 10-bit sensor mode**.
- CAM0 is the software timing server; CAM1 is the client. Each sensor is drained
  independently into a bounded queue. Frames are paired using SensorTimestamp.
- Each accepted pair must be within 250 μs. Missing cameras, missing timestamps
  or failure to acquire timing lock fail acquisition; they do not silently
  produce a single-camera capture in dual mode.
- SyncReady is intermittent libcamera metadata. Its last explicit value is
  retained, while timestamp differences are checked on every frame pair.
- Existing short shutter/gain settings and ball detection thresholds are retained.
- Existing buffer settings retain 325 frames per camera, about 1.34 seconds at
  the verified rate. Sensor timestamps retain any frame gaps.
- This is **software synchronization**. It does not establish externally
  validated exposure timing. Service 0.33.0 uses both views for triangulated
  launch estimates after per-camera lens and shared-tag ground calibration;
  physical accuracy still needs reference validation.

Raspberry Pi's [software synchronization documentation](https://www.raspberrypi.com/documentation/computers/camera_software.html#software-camera-synchronisation)
explains why spare sensor frame-rate capacity is needed for timing corrections.

## Verification on this Pi, 2026-09-22

- Both sensors open concurrently and deliver distinct image data.
- At requested 242 fps, a saved real burst contained 325 frames per camera at
  241.57 observed paired fps. Maximum timestamp offset: 40 μs.
- A 30-second run of the full detector and preview pipeline produced 4,832 paired
  frames in its final 20-second measurement window: 241.56 observed fps,
  maximum offset 54 μs, maximum adjacent-frame gap 4.189 ms. Nine previews
  contained both camera images. No physical shot was performed in this check.
- 243, 244 and 245 fps in 10-bit mode stalled during startup. At 280 and 300 fps
  in 8-bit mode, the pair failed the 250 μs timing gate. Requested 242 fps was
  therefore the fastest tested setting that passed the capture checks.
- Old one-camera captures remain readable. New captures place upper frames in
  `camera-secondary/` with their own manifest/contact sheet. The main
  `capture.json` records both camera indexes and each pair's timestamp offset.
- This 2026-09-22 acquisition verification predates service 0.32.0. At that
  time, upper frames did not inherit the lower camera's AprilTag calibration;
  capture the shared tag with both views to save each camera's pose before
  stereo estimates can be used.
- 197 Python tests passed on the Pi with test calibration/storage paths isolated
  from production data. App type checking, lint and the fragmented BLE client
  integration check passed. Phone rendering/reception and a physical golf strike
  have not been verified in this setup session.
- The deployed service restarted successfully with zero automatic restarts;
  both snapshot files update and the detector reaches waiting-for-ball state.

## Installation and rollback

The Pi boot camera configuration is v0.2.0, with both `dtoverlay=ov9281,cam0`
and `dtoverlay=ov9281`. The existing SSH connection is
`lm1@192.168.0.140`, using `~/.ssh/lm1_codex_ed25519` on the Windows host.

The normal Pi installer includes the updated camera modules and preserves
existing environment settings. To enable the verified profile on this already
provisioned Pi, copy the service folder and run:

```sh
sudo python3 scripts/setup-dual-camera-v1.0.0.py raspberry_pi
```

The setup script backs up the four changed service files, environment and boot
configuration under `/var/lib/pinpoint/backups/pre-dual-0.30.0-*` before replacing
service files. It sets `PINPOINT_DUAL_CAMERA=true`, primary index 0, secondary
index 1, requested 242 fps and 10-bit mode. It restarts the service.

To return to one camera, set `PINPOINT_DUAL_CAMERA=false` in
`/etc/default/pinpoint` and restart `pinpoint`. To roll back code, stop the
service, restore the four Python files and `pinpoint.env` from the printed
backup location, then start it. The second boot overlay can remain enabled.

The diagnostic scripts must run while the service is stopped, with a shell
trap to restart it on exit. Hardware test captures live separately from shot
history in `/home/lm1/dual-camera-0.30.0/`.
