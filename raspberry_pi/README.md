# LM1 PRO Raspberry Pi BLE Service

Service **0.45.0**, protocol **2.31.0**: three clean paired stereo ball frames are sufficient for measured-grade speed, launch angle, and direction when all timing, geometry, calibration, and fit-quality gates also pass. Two paired frames remain an estimated speed-only fallback.

Service **0.44.0**, protocol **2.30.0**: putting captures can emit a putt result when ball and putter motion are resolved even if face strike is unavailable. An unavailable strike is `null`; `airborne` flags launch above 10° so the app does not present a ground-roll estimate for it.

Service **0.43.0**, protocol **2.29.0**: status reports the active capture mode so the app can show whether the Pi is set to a normal shot or putting, including after reconnecting. The app can switch modes in one tap before a ball is placed.

Service **0.42.0**, protocol **2.28.0**: full shots save up to 48 frames after the measured departure (plus any later tracked ball frame), discarding the empty detector-confirmation tail. Putting retains the full rolling burst. The Pi still observes the confirmation window before it reports a shot. Set `PINPOINT_FULL_SHOT_TAIL_FRAMES` to tune the saved full-shot tail.

Service **0.41.0**, protocol **2.28.0**: a signed-in app can issue a short-lived
ticket for one shot, then ask the Pi to upload every retained original JPEG from
both cameras directly to the Supabase frame ingest function. The ticket is
limited to that shot and expires after six hours. Set
`PINPOINT_SUPABASE_PROJECT_REF` in `/etc/default/pinpoint` for this feature.

Service **0.40.0**, protocol **2.27.0**: two high-quality stereo ball frames may
yield estimated interval-average ball speed, using the resting-ball impact
bracket as a consistency check. Two frames cannot resolve the flight curve,
so launch angle, direction, and carry remain unavailable.

Service **0.39.1**, protocol **2.26.1**: capture summaries distinguish a valid
mono fallback from shots where both stereo and mono tracking failed.

Service **0.39.0**, protocol **2.26.0**: the lower camera arms only when the
whole resting ball fits in the left-half green placement zone. The right half
remains available for outgoing tracking; the upper camera must still see the
resting ball and early flight. The stock ROI is `0,0.30,0.50,0.98`.

Service **0.38.1**, protocol **2.25.1**: tag-free club silhouette speed and
attack angle are retained for the selected club. Only an explicitly calibrated
club marker for a different club invalidates those values.

Service **0.38.0**, protocol **2.25.0**: full-shot carry now uses a
still-air drag/lift flight model. The selected club, ball speed and measured
attack angle set provisional spin when surface spin cannot be tracked.
`carryModel` records which spin source was used; landing is never observed.

Service **0.36.0**, protocol **2.23.0**: valid stereo geometry now supplies the
launch vector directly. Ball movement without resolved club motion is retained
as a capture, not emitted as a full shot. Ground recalibration invalidates the
previous target line; roll a fresh ball toward the target afterward. Keep the
entire resting ball, plus a little background, visible in both camera views.

Service **0.35.0**, protocol **2.22.0**: failed stereo tracks retain matched frame
indices and rejection counts for the app's capture review.

Service **0.34.0**, protocol **2.21.0**: stereo launch can use three validated paired
frames as an estimate, while three are needed for measured-grade metrics. A second
circle-detection pass recovers weak ball edges only when normal stereo pairing fails.

Service **0.33.0**, protocol **2.21.0**: when both camera lens and shared-ground-
tag calibrations are present, launch analysis triangulates the ball in both
views. If the lower-camera track fails, each view detects the ball independently
and pairs candidates using ray geometry and a coherent 3D path. It checks
tag-pose age, pair timing, resting position, ray agreement and two-view
reprojection before reporting a result. See
[dual-camera setup](../DUAL_CAMERA_SETUP.md) for calibration and limits.

Service 0.26.0 / protocol 2.17.0: speed, launch angle and direction come from an anchored trajectory fit to up to 48 sub-pixel tracked frames. It starts from the resting ball's ground position, chooses between a ground roll and a gravity flight, re-estimates the start of a ball nudged before release and reports fit uncertainty. Contact analysis ignores a hand or finger that stays in view. A departure must start at the resting ball, the resting ball must not reappear afterwards, and the motion nearest the trigger wins. A ball armed while the placing hand still touched it now tracks from a clean resting image. A ball that stays at resting height is reported as a ground roll with 0-degree launch, measured along the ground plane. The armed-ball reference stays paired with its original bounding box, refreshes only while the ball rests there, and is saved losslessly for replay. captures now retain calibration and outline-rejection diagnostics, and failure messages distinguish camera frames from usable 3D outlines. contact analysis now re-anchors slightly shifted resting balls and rejects stationary offset matches as outgoing motion. reconnect history is bounded to the newest ten records so the 100 retained captures cannot overflow one BLE message. The default ball-detection region covers 90% of the frame width and 68% of its height while retaining a small edge safety margin. Keep hands, clubheads, screens and moving shadows out of that region whenever possible. Tracker-guided partial silhouettes can produce explicitly lower-confidence launch estimates only after three consecutive matches, stable apparent radius and the existing 3D fit check. The strict full-silhouette path remains the default. Saved manifests now retain exact ball bounds for replay. The service also selects the best of up to 12 static ground-AprilTag detections; poses from 1–3 px reprojection error remain explicitly lower-confidence estimates and anything worse is rejected. It includes seam-split silhouette repair, convex-hull ball depth fitting, half-resolution ball tracking (analysis ~2 s instead of ~6 s), MTU-sized BLE notifications, no previews during result delivery, ~1.35 s rolling bursts by default, background AprilTag/focus/snapshot/BLE-preview work, an 8-request camera queue, per-capture contact sheets, live persistent exposure/gain controls, contact-window detection, AprilTag-referenced launch estimates, club-marker tracking, surface spin and putting motion analysis. The Pi retains the newest 100 rolling captures by default. See [measurement setup](../LAUNCH_MEASUREMENTS.md). Values remain unvalidated estimates.



Current service 0.42.0 · BLE protocol 2.28.0


This is the BLE-only Raspberry Pi half of Pinpoint. It opens no Pinpoint network port. The app can connect, arm, trigger, and receive synthetic shots or putts before the camera arrives, while Wi-Fi remains available for internet, SSH, software updates, and OpenGolfSim.



Synthetic results prove communication only. They are not measurements. When a USB webcam is attached, test mode also captures a real diagnostic JPEG so the camera path, framing, lighting, and exposure can be checked before the high-speed camera arrives.



Version 0.2.6 supports an automatic test loop: begin with an empty hitting area, wait for calibration, and place a ball inside the configured region. A ball that remains in the same location and at a consistent size changes the app state to **Armed**. Removing it changes the state to **Processing**, saves the last frame that contained the ball, and sends a synthetic result to the phone.



Version 0.3.0 sends a 160×120 grayscale placement preview to the LM1 app every three seconds over the existing BLE event channel. The app draws the configured detection area and target over the image. No Wi-Fi connection or camera web server is required.



Version 0.4.0 lets the LM1 app scan nearby Wi-Fi networks and ask Raspberry Pi OS NetworkManager to save and join one over BLE. Credentials are sent only in the connect command, are not returned to the app, and are not written to the service log.



## Prepare Raspberry Pi OS



In Raspberry Pi Imager, choose **Raspberry Pi OS Lite (64-bit)**. In customization:



1. Choose any hostname and create your own username/password.

2. Configure Wi-Fi or use Ethernet so the Pi can download the initial packages.

3. Enable SSH.



Bluetooth does not require the phone and Pi to share a Wi-Fi network. A suitable Raspberry Pi 5 USB-C power supply is recommended because under-voltage can cause unreliable radio and camera behaviour.



## Copy and install the service



From PowerShell in the project directory, replace `YOUR_PI_USER` and the hostname if needed:



```powershell

scp -r .\raspberry_pi YOUR_PI_USER@launchmonitor.local:~/pinpoint-setup

ssh YOUR_PI_USER@launchmonitor.local

```



Then run on the Pi:



```bash

cd ~/pinpoint-setup

chmod +x install.sh

sudo ./install.sh

```



The installer enables BlueZ and NetworkManager, installs the Python environment, removes the previous Pinpoint HTTP/mDNS service if present, and starts the BLE peripheral automatically at boot. Run the same installer again to update it.



If service 0.3.0 is already installed but the Pi has no internet, copy this folder to the Pi over temporary Ethernet or removable storage and reuse the existing packages:



```bash

cd ~/pinpoint-setup

sudo ./install.sh --offline

```



Offline mode requires the existing `/opt/pinpoint/.venv`, Bless dependency, and Raspberry Pi OS NetworkManager. It updates the service files and restarts LM1 without downloading packages.



The one-time 0.3.0 → 0.4.0 upgrade cannot be transferred through the old BLE protocol itself. After 0.4.0 is installed, Wi-Fi can be configured from the phone without SSH, Ethernet, or a monitor.



## Verify the Pi



```bash

systemctl status pinpoint --no-pager

bluetoothctl show

journalctl -u pinpoint -n 50 --no-pager

```



The service log should say that `LM1 PRO` is advertising. `bluetoothctl show` should report `Powered: yes`.



To confirm that Pinpoint no longer listens on the network:



```bash

sudo ss -lntup

```



SSH and other normal OS services may still appear, but there should be no Python process listening on port 80.



## Build the mobile app without a Mac



BLE uses native phone APIs and therefore cannot run inside Expo Go. Install a Pinpoint development build instead.



### Android from Windows



The simplest local route is Android Studio plus USB debugging:



```powershell

npm install

npm run android

```



This creates and installs the native Android app on the connected phone. No paid developer account is required.



Alternatively, use Expo's cloud build:



```powershell

npx eas-cli login

npx eas-cli build:configure

npm run build:android:dev

```



Open the build link on the Android phone and install the APK.



### iPhone from Windows



Expo's cloud can build iOS without a Mac, but Apple requires an Apple Developer account for signing and installing this custom BLE build:



```powershell

npx eas-cli login

npx eas-cli build:configure

npm run build:ios:dev

```



After installing either development build, start the JavaScript development server with `npm start` and open the Pinpoint development app.



## Connect and test



1. Keep the phone within a few metres of the Pi and enable Bluetooth.

2. Open **Device** and select **Find Pinpoint over Bluetooth**.

3. Allow the Bluetooth permission when prompted.

4. Confirm **Pi communication is working**.

5. Open **Wi-Fi setup**, scan, select a network, enter its password, and choose **Connect LM1 to Wi-Fi**.

6. Select **Arm**, then **Send test shot**.

7. Open Monitor and confirm a **Synthetic link test** result appears.



Wi-Fi remains connected throughout this process and can send the result to OpenGolfSim.



## Settings



Settings live in `/etc/default/pinpoint`:



```bash

PINPOINT_NAME="LM1 PRO"

PINPOINT_BLE_NAME="LM1 PRO"

PINPOINT_CAPTURE_BACKEND=simulator

PINPOINT_APRILTAG_ID=0

PINPOINT_APRILTAG_SIZE_MM=100

PINPOINT_CAMERA_DEVICE="/dev/v4l/by-id/usb-example-video-index0"

PINPOINT_CAMERA_RESOLUTION=1280x720

PINPOINT_CAMERA_FPS=30

PINPOINT_EXPOSURE_US=15700

PINPOINT_AUTO_BALL_DETECTION=true

PINPOINT_BALL_ROI="0,0.30,0.50,0.98"

PINPOINT_BLE_PREVIEW=true

PINPOINT_BLE_PREVIEW_INTERVAL_SECONDS=3

PINPOINT_CAPTURE_RETENTION=100

PINPOINT_WIFI_PROVISIONING=true

PINPOINT_WIFI_INTERFACE=wlan0

```



Apply changes with `sudo systemctl restart pinpoint`. Set `PINPOINT_WIFI_PROVISIONING=false` after setup when the device will be used in a shared or public space; the current MVP BLE link is proximity-only and not authenticated. Keep the short BLE name because advertising packets have limited space. Keep the simulator backend until the real camera capture module is installed. The installer records the first stable USB camera `video-index0` path it finds. Each test trigger then replaces `/var/lib/pinpoint/usb-test-latest.jpg` with a fresh frame and reports `frameCount: 1`, while `simulated: true` remains set because the shot numbers are synthetic.



`PINPOINT_BALL_ROI` is `left,top,right,bottom`, expressed from `0` to `1` across the camera frame. Keep hands, clubheads, screens, and moving shadows outside this rectangle when possible. Restart the service with an empty hitting area whenever the camera is moved.



Inspect the most recent diagnostic frame from another computer with:



```powershell

scp YOUR_PI_USER@launchmonitor.local:/var/lib/pinpoint/usb-test-latest.jpg .

```



## Main files



```text

pinpoint_ble.py          BlueZ/Bless GATT peripheral and notification framing

pinpoint_protocol.py     Commands, state, history, and synthetic capture backend

wifi_manager.py          NetworkManager Wi-Fi scan, status, and connection adapter

ball_detector.py         Debounced USB-camera ball placement/removal detector

install.sh               Repeatable Raspberry Pi OS installer/updater

systemd/                 Automatic startup and restart policy

tests/                   Transport-independent BLE protocol tests

```



## OV9281 on CAM0 (service 0.5.0)



Install `python3-picamera2` through apt (included by the online installer). The existing venv must expose system site packages. Offline installation needs Picamera2 already installed for CSI use.



With the ribbon attached to CAM0, boot configuration `/boot/firmware/config.txt` needs an `[all]` section containing `camera_auto_detect=0` and `dtoverlay=ov9281,cam0`. Back up the file before changing it and reboot once. Confirm with `rpicam-hello --list-cameras`.



Set these in `/etc/default/pinpoint` and restart `pinpoint`:



```bash

PINPOINT_CAMERA_SOURCE=csi

PINPOINT_CAMERA_INDEX=0

PINPOINT_CAMERA_RESOLUTION=1280x800

PINPOINT_CAMERA_FPS=30

PINPOINT_EXPOSURE_US=0

PINPOINT_DETECTOR_WIDTH=640

PINPOINT_DETECTOR_HEIGHT=400

PINPOINT_BLE_PREVIEW_WIDTH=160

PINPOINT_BLE_PREVIEW_HEIGHT=100

PINPOINT_BLE_PREVIEW=true

PINPOINT_CAPTURE_BACKEND=simulator

```



Exposure 0 enables automatic exposure; a positive value uses manual microseconds with `PINPOINT_CAMERA_GAIN` (default 1). `PINPOINT_CAMERA_INDEX=0` selects the first enumerated libcamera sensor, not the physical connector number. The boot overlay determines CAM0. `PINPOINT_CAMERA_DEVICE` is ignored for CSI.



For focus setup, set `PINPOINT_AUTO_BALL_DETECTION=false`: the preview continues without automatic shot triggers. Enable it again with an empty hitting area after positioning/focusing. The CSI stream runs at full resolution; detection uses a smaller copy and BLE sends a bounded 160×100 JPEG every three seconds. The same stream atomically saves `/var/lib/pinpoint/camera-latest.jpg` for full-resolution inspection. Do not start a second rpicam process while the service owns the camera.

The Device screen can change CSI exposure live from 20–250 μs while LM1 is ready. Changes are rejected while armed or processing so a capture cannot mix exposure settings. The selected value is saved atomically in `/var/lib/pinpoint/camera-settings.json`, overrides `PINPOINT_EXPOSURE_US` on later starts, and stays within the current launch-measurement exposure gate.

The same screen can change OV9281 analogue gain from 1×–16× in 0.25 steps while manual exposure is active. Higher gain brightens the frame but also amplifies noise, so prefer more lighting and the lowest gain that exposes the ball clearly. The selected value is stored with exposure in `camera-settings.json`, overrides `PINPOINT_CAMERA_GAIN` on later starts, and remains in effect when exposure changes.



Open Device in the app for the camera model, capture settings, preview and relative sharpness reading. Put a printed target at the intended ball distance in the green ROI. For a lens without autofocus, gently adjust its focus mechanism while keeping framing and lighting fixed; use the full-resolution snapshot to confirm details. A higher sharpness score can also reflect noise or different scenery, so it is not an absolute pass/fail grade.



```powershell

scp -i "$env:USERPROFILE/.ssh/lm1_codex_ed25519" lm1@192.168.0.140:/var/lib/pinpoint/camera-latest.jpg .

```



These settings verify the camera and positioning. They do not implement measured launch speed, angle or spin.


## AprilTag calibration (0.12.0)

Print `output/pdf/lm1-apriltag-36h11-id0-100mm-v1.0.0.pdf` at 100% and verify its 100 mm ruler. Place the tag flat beside the ball with its top edge parallel to the intended target line. The Calibration screen outlines a detected tag and reports detection quality. **Capture AprilTag calibration** persists `/var/lib/pinpoint/apriltag-calibration.json`.

The saved record contains normalized image corners, pixels per millimetre, target-line rotation, perspective distortion, and a 3 × 3 homography that maps full camera pixels onto the tag plane in millimetres. Each later rolling capture copies this record into its `capture.json`, keeping the frame burst and its physical reference together for trajectory analysis. Set `PINPOINT_CAMERA_FOCAL_LENGTH_PX` after an intrinsic camera calibration if you also want an estimated camera-to-tag distance. Re-capture whenever the camera or tag moves.

AprilTag geometry gives the later trajectory analyzer a real scale and planar perspective correction. Current shot and putting numbers remain explicitly synthetic until the measurement backend consumes captured ball/club tracks.


## Ball detection overlay (0.6.0)

Set `PINPOINT_AUTO_BALL_DETECTION=true` to enable detection. For the 200 fps setup use `PINPOINT_BALL_FRAME_STRIDE=20`, `PINPOINT_BALL_CALIBRATION_FRAMES=30`, `PINPOINT_BALL_PRESENT_FRAMES=8`, and `PINPOINT_BALL_ABSENT_FRAMES=5`. Restart with the green ROI empty and wait for Waiting for ball before placing a ball there. Moving the camera requires a restart and empty-area calibration. The detector identifies a newly placed round object relative to its background, not semantic object identity.

The camera overlay shows Ball detected after stable placement and draws a box in the same preview image. It updates with the three-second BLE snapshot. During removal debounce it retains the last confirmed box. At 200 fps, service 0.7.0 samples detection at 50 Hz by default to reduce missed balls under flickering indoor lighting. Stale previews stop claiming detection. Automatic arming/removal still produces synthetic shot values.

## Analysis denoising (0.25.0)

Departure analysis uses a gentle per-frame bilateral filter (5 px, sigma colour 12, sigma space 3), also applied to the armed reference. Raw saved frames and displayed evidence stay unchanged. Set PINPOINT_ANALYSIS_DENOISE=none in the service environment and restart to disable. Filter time and parameters appear in capture diagnostics. Replay showed improved tag pose fit but no extra trajectory frames or spin, and worse radius fit; physical accuracy remains unvalidated. Filtering happens after capture, adding processing time rather than reducing camera acquisition FPS.

## Stored ground calibration (0.26.0)

Reset empty plane with the ball removed, then place the ground tag flat and fully visible and use Capture AprilTag calibration. Lens calibration at the exact current resolution must exist first. Successful capture saves 3D ground pose and lens inputs; you may remove the ground tag afterward. Keep camera position, focus, capture mode and surface fixed. Empty-plane reset and successful lens recalibration clear ground geometry and target line. Recalibrate with the tag again, then set target line from a roll. Old planar-only saved records are insufficient for tag removal. With no stored pose, a visible ground tag retains the previous burst fallback. Stored-pose diagnostics are retained in each analysis.
