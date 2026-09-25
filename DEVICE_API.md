# Pinpoint Device BLE Protocol



Protocol version 2.31.0

Protocol 2.31.0 permits a three-frame stereo trajectory to receive measured-grade status when every timing, geometry, calibration, and fit-quality gate passes. Protocol 2.30.0 permits `putt.strike: null` when face contact is unavailable and adds `putt.airborne` for launch above 10°. Ball/putter speed, smash and launch inputs are still required before a putt result is emitted.

Protocol 2.29.0 adds `captureMode` (`full-shot` or `putting`) to status responses and status events. Clients should use this device-reported value when showing the active mode after reconnecting. Sending `arm` with a different mode switches modes while armed, provided a capture is not processing; the app also waits until the ball is removed.

Protocol 2.27.0 permits a `shared-tag-stereo-two-point-v1` speed-only estimate.
Capture `tracking.status` is `stereo-two-point`, with `speedOnly: true` and
`speedUncertaintyPct`; launch angle, direction, and carry remain unavailable.
The resting-ball/impact bracket checks the two-point path but is not treated
as an exact third timed observation.

Protocol 2.26.1 adds `tracking.monoFallback`, `tracking.stereoFailure`, and
`tracking.monoFailure` to capture summaries. `tracking.source` is null when no
ball speed survived validation; a rejected stereo fit does not count as a
stereo-matched measurement.

Protocol 2.26.0 changes the default lower-camera placement `preview.roi` to
`[0,0.30,0.50,0.98]` and its `preview.target` to `[0.25,0.72]`. This is a
placement/arming region only; outgoing-ball analysis continues across the full
frames from both cameras. Custom `PINPOINT_BALL_ROI` values remain supported.

For the fixed left-to-right rig, `startDirectionDeg` remains a signed number:
positive is right/toward the cameras, negative is left/away, and zero is the
bottom camera's across-image target line. This is a display clarification in
app 3.18.2, not a protocol sign change.

Protocol 2.25.1 preserves tag-free club measurements when no club-marker
profile ID is attached to the capture. A present marker profile ID still must
match the selected club. The returned metric values and confidence retain the
camera's estimated provenance.

Protocol 2.25.0 adds `capture.measurements.carryModel` with `version`,
`spinSource`, `spinRpmUsed`, and `attackAngleDegUsed`. `estimatedCarryM` is
always a modeled still-air target-line distance to the launch-height plane;
it is never a measured landing. Missing spin uses the selected club's average,
scaled for ball speed and adjusted for attack angle only when that angle was
resolved. Wind, terrain, spin-axis curvature and landing-height differences
are not included.

Protocol 2.23.0 adds `measurements.shotEvidence` (`status`: `club-motion-observed`
or `motion-only`, `clubFrames`, `reason`) and `measurements.tracking.source`
(`stereo` or `single-camera`). Full-shot consumers must not promote or send a
`motion-only` capture as a shot. Putting still accepts resolved ground motion.
The matched-pair count describes detection evidence; `source` identifies the
fit actually used for the returned launch metrics.

Protocol 2.32.0 changes the meaning of `motion-only`: the ball was measured but no
pre-impact club track was resolved. Such a capture is a shot with club speed,
smash and strike unavailable. A new full-shot status, `not-a-strike`, marks
movement that cannot be a strike (ball speed under 2 m/s, direction more than 60°
off the target line, or a ground roll with no club seen); consumers must not
promote or send it. Putting captures are never classified this way.

Protocol 2.34.0 adds named clubs. `setClub` and `arm` accept an optional
`"bagClub": {"id": "bag-...", "name": "Vokey 56", "faceWidthMm": 78, "faceHeightMm": 50}`
(id 1-64 of letters, digits, `-`, `_`; name 1-40 characters; face size optional but both or
neither, 55-135 x 20-80 mm). `clubId` stays the club type. Captures and legacy shot events then
carry `bagClubId` and `bagClubName`, and `status.selectedBagClub` reports `{id, name}` or null.
A face size is written to the club profile with `"source": "app"`; a profile without that
marker is never replaced or removed. Omitting `bagClub` clears the named club.

Protocol 2.32.0 also adds pre-shot readiness. When a ball arms, the Pi checks the
resting ball in both cameras and sends
`{"type":"readiness","data":{"version":1,"status":"ok|warn|fail","items":[...],"checkedAt":"..."}}`.
Each item has `id` (`exposure`, `ground`, `stereo-rest`, `club-profile`), `label`,
`status` and a `detail` saying what will fail and how to fix it; `stereo-rest` also
reports `offsetPx`, `rayGapMm` and `heightErrorMm`. The same object is returned as
`status.readiness`, re-evaluated for the current club and mode (null on the
simulator backend). It is advisory and never blocks a capture.

Protocol 2.22.0 adds a bounded `capture.measurements.tracking` summary to BLE
capture events and `listCaptures`: `status` (`failed`, `stereo-matched`, or
`single-camera`), `lowerFrames`, `pairedFrames`, `pairedFrameIndices`, `spanMs`,
`detection`, `imageResidualPx`, `failure`, and candidate `rejections`. Full
per-frame geometry stays in saved `analysis.json`. A failed track has null
physical metrics; the app does not replace missing ball speed with a club
profile or send it as a simulator shot. Three stereo pairs can produce an
estimate, while at least three clean pairs are required for measured-grade status.

Pi service 0.33.0 adds an optional stereo launch path without changing the BLE
contract. When both cameras have valid lens intrinsics and saved AprilTag poses,
paired ball detections can triangulate depth and recover speed, launch and start
direction even when the monocular ball track or outline fit fails. The capture's
`measurements.method` and `measurements.diagnostics.stereo` identify this path;
missing calibration or failed stereo quality gates leave the metrics
unavailable. The upper pose must be within five seconds of the lower pose, and
each paired exposure must be within 250 μs.

Protocol 2.17.0: `{"type":"status","mtu":247}` states the connection's negotiated ATT MTU (23–517). The Pi then sends notification chunks of `min(244, mtu - 3)` bytes and reports `notificationChunkBytes` in status; a status request without `mtu` restores 20-byte chunks. Send it first on every connection.

Service 0.15.0 adds `capture.measurements`: a `method` string, per-field `metrics` with `value` (number or null), `unit`, `status` (`estimated`/`unavailable`), and `reason`. Full 3D/spin traces are stored in Pi `analysis.json`; the BLE summary omits them to bound transfer size. Complete core results also emit the existing shot/putt shape with `simulated: false` and `measurementSource: monocular-estimate`. Optional metrics are omitted when unavailable. Reported metrics also carry `confidence` (0.05–0.95) and `checks` (`[{label, passed}]`); `status` is `measured` only when every check passed, otherwise `estimated`. Confidence is a quality grade, not a calibrated error bound. See LAUNCH_MEASUREMENTS.md for setup and coordinate conventions.

Service 0.27.0 adds `clubPathDeg` and `attackAngleDeg` to `metrics`, using the same value/unit/status/reason shape, so existing consumers need no change and may ignore them. The tag-free clubhead path supplies `clubSpeedMps`, `smashFactor` and `attackAngleDeg` when no club AprilTag is calibrated; `clubPathDeg` comes only from a calibrated club tag, because the silhouette path's swing plane is defined by the ball's own direction and a path taken from it would merely restate `startDirectionDeg`. `diagnostics.clubSilhouette` reports method, candidate and accepted frame counts, fit residual and, when resolved, shaft lean. Everything on this path is an estimate whose reason names the swing-plane assumption behind it, and `strikeXmm`/`strikeYmm` additionally require a measured `club-profile.json` rather than being inferred.

Start direction now defaults to a target line taken from the camera's across-image axis, so it no longer requires the rolled-ball calibration; `diagnostics.calibration.targetHeadingSource` is `camera-axis` or `rolled-ball`, and a saved explicit line still wins. Captures also carry `targetLineSource` alongside `targetLineHeadingDeg`.

Camera workflow (service 0.23.2): the default detection ROI is `[0.05,0.30,0.95,0.98]`, covering 61.2% of the camera frame. Status includes `automaticCapture` and, for CSI cameras, `exposureControl` and `gainControl` capability metadata. `autoCalibrateExposure` (service 0.28.0) measures the current lighting and picks both values automatically; manual control is unaffected. `setExposure` applies and persists a measurement-safe 50–250 μs manual exposure; `setGain` applies and persists OV9281 analogue gain from 1×–16× while manual exposure is active. Both commands require the device to be ready. Automatic camera departures emit `capture` events containing `id`, optional `captureId`, `capturedAt`, `clubId`, `mode`, `classification`, `frameCount`, `captureDurationMs`, `measuredFps`, backward-compatible `impactFrameIndex`, `coarseDepartureFrameIndex`, nullable `lastStationaryFrameIndex` and `firstMovingFrameIndex`, `imageFrameIndex`, `track`, `warnings`, and a bounded JPEG `image` (`mimeType`, `base64`). Measurements can include `tagPoseFrameIndex`, `tagPoseReprojectionErrorPx`, and quality warnings: the best of up to 12 static ground-tag detections is used, 1–3 px poses are labeled lower-confidence, and poses above 3 px are rejected. When the strict full-disc silhouette path cannot resolve three points, a tracker-guided partial-silhouette fallback may estimate launch only after independent image-plane agreement, three consecutive frames, stable apparent radius and the existing 8 mm 3D fit gate. Saved `capture.json` manifests include `ballBounds` for exact offline replay. A resolved contact window spans the last resting-ball frame and first coherent moving-ball frame; the coarse trigger is diagnostic and is not impact. Classification is `motion-observed` or `unconfirmed-departure`, never a claim of measured club contact. Unsupported physical metrics are omitted. `listCaptures` retrieves the newest ten records, including images; the Pi retains 100 captures by default, configurable with `PINPOINT_CAPTURE_RETENTION`. Use a 60-second BLE timeout. Existing `captureFrame` retrieves a frame from the named burst and includes all marker fields. Unsolicited `error` messages must be displayed. Automatic capture disables manual synthetic triggering. Explicit demo/test mode keeps the existing synthetic `shot`/`putt` contract.



The mobile app is the Bluetooth Low Energy (BLE) **central** and the Raspberry Pi is the BLE **peripheral**. Pinpoint device traffic does not use Wi-Fi, HTTP, TCP, or WebSockets. The phone and Pi may independently keep Wi-Fi connected for OpenGolfSim, internet access, SSH, and updates.



## GATT service



| Item | UUID | Direction |

|---|---|---|

| Pinpoint service | `7f510000-1b15-4d8d-8d9c-5f7b6a210001` | Advertised by Pi |

| Command characteristic | `7f510001-1b15-4d8d-8d9c-5f7b6a210001` | App writes with response |

| Event characteristic | `7f510002-1b15-4d8d-8d9c-5f7b6a210001` | App subscribes to notifications |



The Pi advertises the local name `LM1 PRO`. Only one app connection is expected in the MVP.



## Framing



Each logical message is one compact UTF-8 JSON object followed by a newline (`0x0A`). Both sides split outgoing data into chunks of at most 20 bytes, so the protocol works with BLE's minimum 23-byte ATT MTU. The receiver joins chunks until it sees the newline, then parses the complete JSON object.



Maximum app command size is 4096 bytes. The Pi uses ASCII JSON escapes for non-ASCII text so a multi-byte character is never divided between notifications.



## Commands and responses



Every command contains a short string `id`. Its response contains the same `id`.



Status request:



```json

{"id":"1","type":"status"}

```



```json

{"type":"response","id":"1","data":{"name":"LM1 PRO","state":"ready","firmwareVersion":"0.4.0","protocolVersion":"2.2.0","transport":"ble","wifiProvisioning":true,"captureBackend":"simulator","cameraConnected":true,"fps":30,"exposureUs":15700,"temperatureC":48.2,"storageFreeGb":22.6,"calibrationVersion":"NOT-CALIBRATED","lastSeenAt":"2026-09-04T10:30:00.000Z","preview":{"transport":"ble","intervalMs":3000,"width":160,"height":120,"roi":[0.05,0.30,0.95,0.98],"target":[0.5,0.72]}}}

```



Supported commands:



- `{"id":"2","type":"listShots"}` returns the newest 10 shots.

- `{"id":"3","type":"listPutts"}` returns the newest 10 putts.

- `{"id":"4","type":"arm","clubId":"driver","mode":"full-shot"}` returns status.

- `{"id":"5","type":"arm","clubId":"putter","mode":"putting"}` returns status.

- `{"id":"6","type":"disarm"}` returns status.

- `{"id":"7","type":"trigger"}` returns `{"accepted":true}` and starts live events.

- `{"id":"8","type":"wifiStatus"}` returns the connected SSID, signal, and Wi-Fi IPv4 address without returning credentials.

- `{"id":"9","type":"wifiScan"}` returns up to 12 nearby SSIDs with signal, security, support, and connected flags.

- `{"id":"10","type":"wifiConnect","ssid":"Home Wi-Fi","password":"example-password","hidden":false}` asks NetworkManager to save and join the network. The password is never included in the response or service logs.

- `{"id":"11","type":"captureAprilTagCalibration"}` saves the latest visible AprilTag 36h11 ID 0 geometry and returns its normalized corners, physical scale, rotation, perspective quality, and image-to-tag millimetre homography.

- `{"id":"12","type":"resetBallCalibration"}` restarts empty-plane learning without restarting the service.

- `{"id":"13","type":"latestCapturePreview"}` returns the latest rolling impact contact sheet.

- `{"id":"14","type":"setClub","clubId":"7-iron"}` updates the club used by automatic ball-triggered captures without manually arming the device.

- `{"id":"15","type":"captureFrame","captureId":"capture-123","frameIndex":60}` returns one compact frame from the exact rolling burst attached to a shot, including its frame timestamp and estimated departure index.
- `{"id":"16","type":"captureContactSheet","captureId":"capture-123"}` (service 0.17.0) returns `mimeType`, `base64` and `captureId` for that burst's saved 12-frame `contact-sheet.jpg` (about 25–40 KB of base64). Invalid, pruned or sheet-less captures return an error. Use a 45-second BLE timeout.
- `{"id":"17","type":"uploadCaptureFrames","captureId":"capture-123","frameCount":250,"ticket":"<short-lived-ticket>","indices":[0,1,2]}` (service 0.41.0) starts an HTTPS upload of the original JPEGs retained on the Pi. The Pi posts both camera files for each index to Supabase using a shot-scoped ticket and returns `{captureId,uploaded,total,state}` immediately. It emits `frameUploadProgress` events every ten frames and on completion or error. `captureFrameUploadStatus` returns the current upload state. The app supplies only missing indices when resuming an interrupted upload. `PINPOINT_SUPABASE_PROJECT_REF` must be configured on the Pi.

- `{"id":"16","type":"setExposure","exposureUs":180}` applies a live manual CSI exposure from 20–250 μs, persists it across restarts, returns updated status, and emits a status event. LM1 must be ready (not armed or processing).

- `{"id":"17","type":"setGain","gain":2.5}` applies live OV9281 analogue gain from 1×–16×, persists it across restarts, returns updated status, and emits a status event. Manual exposure must be active and LM1 must be ready.

- `{"id":"18","type":"autoCalibrateExposure"}` (service 0.28.0) asks LM1 to measure the room and choose exposure and gain itself. It returns `{"accepted":true}` immediately; the sweep runs in the detection loop, which borrows its own frames rather than opening the camera twice. The chosen pair is applied and persisted exactly as `setExposure`/`setGain` would, and the outcome arrives as an `exposureCalibration` event followed by a `status` event. Requires a CSI camera and a ready (not armed or processing) device. Use a 30-second BLE timeout.

The `exposureCalibration` event payload is `{"ok":true,"exposureUs":90,"gain":1.5,"meanBrightness":103.4,"clippedFraction":0.0012,"usable":true,"samplesTaken":8,"note":"Matched the light in the room."}`, or `{"ok":false,"error":"..."}` when the sweep could not finish. The search probes a spread of shutter speeds at 1× gain and keeps the **shortest** exposure whose frame is bright enough and not clipped, because motion blur costs more accuracy than grain does; only if every allowed exposure is still dark does it raise analogue gain. `usable:false` means the room itself is the limit — the note says whether to add light or shade the hitting area. Manual `setExposure`/`setGain` are unchanged and override the result at any time.



A rejected command returns:



```json

{"type":"error","id":"7","message":"A capture is already processing."}

```



## Live events



Status changes use the same status object as the request response:



```json

{"type":"status","data":{"name":"LM1 PRO","state":"armed","firmwareVersion":"0.4.0","protocolVersion":"2.2.0","transport":"ble","wifiProvisioning":true,"captureBackend":"simulator","cameraConnected":true,"fps":30,"exposureUs":15700,"temperatureC":48.2,"storageFreeGb":22.6,"calibrationVersion":"NOT-CALIBRATED","lastSeenAt":"2026-09-04T10:30:00.000Z"}}

```



Analysis progress:



```json

{"type":"processing","data":{"progress":0.65}}

```



Low-resolution placement preview:



```json

{"type":"preview","data":{"mimeType":"image/jpeg","base64":"/9j/4AAQ...","capturedAt":"2026-09-04T10:30:03.000Z"}}

```



The preview JPEG is grayscale, normally 160×120, capped at 2200 binary bytes before Base64 encoding, and sent at most once every three seconds. It is for ball placement only and must not be used for shot measurement.



Completed full shot:



```json

{"type":"shot","data":{"id":"pi-test-a12b","number":1,"capturedAt":"2026-09-03T10:31:09.000Z","clubId":"driver","ballSpeedMps":61.8,"clubSpeedMps":42.4,"smashFactor":1.46,"launchAngleDeg":14.2,"startDirectionDeg":1.8,"strike":{"xMm":7,"yMm":2},"confidence":0.96,"frameCount":220,"captureDurationMs":1095,"captureId":"capture-123","impactFrameIndex":60,"simulated":true}}

```



Completed putt:



```json

{"type":"putt","data":{"id":"pi-test-putt-b34c","number":1,"capturedAt":"2026-09-03T10:35:00.000Z","ballSpeedMps":1.82,"putterSpeedMps":1.28,"smashFactor":1.42,"launchDirectionDeg":0.35,"launchAngleDeg":1.6,"strike":{"xMm":1.5,"yMm":0.5},"confidence":0.97,"frameCount":0,"captureDurationMs":1150,"rollDistanceM":3.05,"skidDistanceM":0.22,"simulated":true}}

```



Direction and strike conventions remain:



- Positive direction is right of the target line; negative is left.

- Positive strike `xMm` is toe; negative is heel.

- Positive strike `yMm` is above face centre; negative is below.

- `spinRpm`, `spinAxisDeg`, `estimatedCarryM`, `rollDistanceM`, and `skidDistanceM` are optional.

- `simulated: true` means the value only verifies communication and is not a camera measurement.

- In simulator mode, an attached USB webcam may supply one real diagnostic frame. A successful frame sets `frameCount` to `1`, but all shot/putt metrics remain synthetic and `simulated` remains `true`.

- With automatic ball detection enabled, a debounced placement emits `state: "armed"`; debounced removal emits `state: "processing"` followed by the same synthetic shot or putt event.



## Connection lifecycle



1. The app scans for the Pinpoint service UUID.

2. It connects, discovers characteristics, and subscribes to the event characteristic.

3. It requests status and history.

4. On an unexpected disconnect it retries the saved BLE identifier, then falls back to scanning.

5. The app never needs the Pi's hostname or IP address for BLE communication; protocol 2.2 can optionally report the Wi-Fi address for maintenance.



## Security and scope



Version 2.2 uses proximity and a single active BLE connection but does not yet require authenticated bonding. Wi-Fi provisioning is intended for private, nearby setup and can be disabled with `PINPOINT_WIFI_PROVISIONING=false`. Before public or shared-space deployment, require encrypted characteristics and authenticated pairing. Placement-preview frames are intentionally low-resolution and bounded; do not use this link for full-resolution camera footage.



## CSI camera diagnostics (2.3.0)



Status and preview data optionally include `camera`: `model`, `width`, `height`, `fps` (derived from sensor FrameDuration), `exposureUs`, `gain`, `autoExposure`, `autofocus`, and `focusScore` (relative Laplacian variance in the placement ROI). Compare focus only with the same target, framing and lighting. CSI status becomes connected only after a real frame and expires after five seconds without frames. The default CSI BLE preview is 160×100; USB remains 160×120. Camera pixels and metadata are real; shot measurements remain synthetic.


## Ball presence (2.4.0)

`preview.data.camera.ballDetection` contains `state` (`calibrating`, `waiting`, `detected`, `disabled`) and `bounds` (normalized left, top, width, height, or null). It describes the accompanying image, independently of manual arming and synthetic shot state. Clients hide detected state on stale/disconnected previews.


## Dual camera extension - protocol 2.20.0 / service 0.30.0

When PINPOINT_DUAL_CAMERA is enabled, preview events optionally include
`secondaryBase64` (JPEG) alongside the unchanged primary `base64`. Camera
metadata includes `cameraCount`, `primaryCameraIndex`, `secondaryCameraIndex`,
`syncMode=software`, `syncReady`, `syncOffsetUs`, `syncToleranceUs`, `pairedFps`,
`secondaryFps`, `secondaryExposureUs` and `secondaryGain`. `pairedFps` measures
accepted timestamp-matched pairs; sensor `fps` is not proof of retained frames.
Both cameras share the lower-camera ball trigger and exposure/gain commands.

Capture events can include `secondaryImage` for the same `imageFrameIndex`.
`captureFrame` responses optionally include `secondaryBase64` and `pairOffsetUs`
for the requested frame index. Single-camera history keeps the old payload.
The existing physical-measurement contract is unchanged: stereo calibration
and triangulation are not implemented by this acquisition update.
