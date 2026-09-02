# Pinpoint Device BLE Protocol

Protocol version 2.0.0

The mobile app is the Bluetooth Low Energy (BLE) **central** and the Raspberry Pi is the BLE **peripheral**. Pinpoint device traffic does not use Wi-Fi, HTTP, TCP, or WebSockets. The phone and Pi may independently keep Wi-Fi connected for OpenGolfSim, internet access, SSH, and updates.

## GATT service

| Item | UUID | Direction |
|---|---|---|
| Pinpoint service | `7f510000-1b15-4d8d-8d9c-5f7b6a210001` | Advertised by Pi |
| Command characteristic | `7f510001-1b15-4d8d-8d9c-5f7b6a210001` | App writes with response |
| Event characteristic | `7f510002-1b15-4d8d-8d9c-5f7b6a210001` | App subscribes to notifications |

The Pi advertises the local name `Pinpoint LM`. Only one app connection is expected in the MVP.

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
{"type":"response","id":"1","data":{"name":"Pinpoint LM · Raspberry Pi","state":"ready","firmwareVersion":"0.2.0","protocolVersion":"2.0.0","transport":"ble","captureBackend":"simulator","cameraConnected":false,"fps":0,"exposureUs":0,"temperatureC":48.2,"storageFreeGb":22.6,"calibrationVersion":"NOT-CALIBRATED","lastSeenAt":"2026-09-03T10:30:00.000Z"}}
```

Supported commands:

- `{"id":"2","type":"listShots"}` returns the newest 10 shots.
- `{"id":"3","type":"listPutts"}` returns the newest 10 putts.
- `{"id":"4","type":"arm","clubId":"driver","mode":"full-shot"}` returns status.
- `{"id":"5","type":"arm","clubId":"putter","mode":"putting"}` returns status.
- `{"id":"6","type":"disarm"}` returns status.
- `{"id":"7","type":"trigger"}` returns `{"accepted":true}` and starts live events.

A rejected command returns:

```json
{"type":"error","id":"7","message":"A capture is already processing."}
```

## Live events

Status changes use the same status object as the request response:

```json
{"type":"status","data":{"name":"Pinpoint LM · Raspberry Pi","state":"armed","firmwareVersion":"0.2.0","protocolVersion":"2.0.0","transport":"ble","captureBackend":"simulator","cameraConnected":false,"fps":0,"exposureUs":0,"temperatureC":48.2,"storageFreeGb":22.6,"calibrationVersion":"NOT-CALIBRATED","lastSeenAt":"2026-09-03T10:30:00.000Z"}}
```

Analysis progress:

```json
{"type":"processing","data":{"progress":0.65}}
```

Completed full shot:

```json
{"type":"shot","data":{"id":"pi-test-a12b","number":1,"capturedAt":"2026-09-03T10:31:09.000Z","clubId":"driver","ballSpeedMps":61.8,"clubSpeedMps":42.4,"smashFactor":1.46,"launchAngleDeg":14.2,"startDirectionDeg":1.8,"strike":{"xMm":7,"yMm":2},"confidence":0.96,"frameCount":0,"captureDurationMs":1150,"simulated":true}}
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

## Connection lifecycle

1. The app scans for the Pinpoint service UUID.
2. It connects, discovers characteristics, and subscribes to the event characteristic.
3. It requests status and history.
4. On an unexpected disconnect it retries the saved BLE identifier, then falls back to scanning.
5. The app never needs the Pi's hostname or IP address.

## Security and scope

Version 2.0 uses proximity and a single active BLE connection but does not yet require authenticated bonding. Use it as a local MVP. Before public or shared-space deployment, require encrypted characteristics and authenticated pairing. Never transmit camera frames over BLE; only status and completed capture results belong on this link.
