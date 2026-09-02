# Changelog

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
