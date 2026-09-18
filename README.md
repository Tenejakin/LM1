# LM1 Launch Monitor Mobile



Version 3.8.1

AprilTag launch measurements and setup: [LAUNCH_MEASUREMENTS.md](./LAUNCH_MEASUREMENTS.md). Version 3.8.1 expands the default Pi ball-detection region to 61.2% of the frame for more flexible ball placement. Version 3.8.0 adds a guarded tracker-guided fallback for partial ball silhouettes while retaining strict temporal, radius and 3D-fit validation. Version 3.7.3 selects the best ground-tag pose from several burst frames and permits explicitly lower-confidence estimates up to a bounded 3 px reprojection error. Version 3.7.2 rejoins ball silhouettes split by the seam line. Version 3.7.1 fits ball depth to the silhouette's convex hull so seam lines and logos no longer block ball speed. Version 3.7.0 cuts Pi shot analysis from ~6 s to ~2 s and sends BLE data in MTU-sized chunks (about 12× faster transfers). Version 3.6.1 shortens the Pi's rolling burst to about 1.35 s and stops preview work from dropping frames. Version 3.6.0 shows each capture's contact sheet on every capture card and shot detail. Earlier releases add live, persistent OV9281 exposure and analogue-gain controls in the Device screen, retain 100 self-identifying rolling captures on the Pi, separate the sampled departure trigger from the full-rate contact window, and include monocular ball/club/spin estimates with per-metric evidence gates and captured imagery. Physical accuracy requires reference validation. Synthetic values remain reserved for explicit demo/link tests.



A React Native + Expo companion app for the Raspberry Pi golf launch monitor described in [`golf_launch_monitor_project.md`](./golf_launch_monitor_project.md).



The app includes:



- A live monitor with ready, armed, processing, and result states

- Ball speed, club speed, smash factor, launch angle, and start direction

- Persistent club selection across woods, hybrids, irons, and wedges

- Estimated carry in metres and yards, with the selected club saved per shot

- A manual calculator page for entering shot measurements and deriving all result metrics

- A dedicated putting monitor with target pace, green speed, start line, skid, and roll-path analysis

- Clubface strike visualization and trajectory visualization

- Shot history, sorting, session averages, and consistency

- Raspberry Pi connection exclusively over Bluetooth Low Energy

- OpenGolfSim Desktop and Web connections with automatic shot forwarding

- Camera, capture, temperature, storage, firmware, and calibration diagnostics

- Persistent device address and automatic reconnection

- Interactive demo mode for testing without hardware

- A camera-free Raspberry Pi service for verifying the real BLE and live-event path

- OV9281 CSI camera preview, full-resolution focus snapshots, and live exposure diagnostics

- Optional USB-webcam diagnostic capture while shot and putting values stay clearly synthetic

- A low-resolution ball-placement preview delivered over BLE every three seconds

- Raspberry Pi Wi-Fi scanning and setup from the Device screen over BLE



## Run it



Requirements: Node.js 20+ and an LM1 native development build on an iOS or Android device. BLE cannot run in Expo Go.



```powershell

npm install

npm start

```



Open the development server from the installed LM1 development app. Android can be built directly on Windows; iOS can be built with Expo's cloud service without a Mac, but requires an Apple Developer account.



Other useful commands:



```powershell

npm run android

npm run ios

npm run web

npm run build:android:dev

npm run build:ios:dev

npm run typecheck

npm run lint

npm run test:ogs

```



Open the **Device** tab and choose **Use interactive demo** to exercise the complete arm → impact → processing → result flow without a Raspberry Pi.



## Connect to the Raspberry Pi



The ready-to-install Pi service is in [`raspberry_pi/README.md`](./raspberry_pi/README.md). It works before the high-speed camera arrives, can save a diagnostic frame from a temporary USB webcam, and generates clearly labelled synthetic results to verify the full app ↔ Pi connection. The app finds the Pi by BLE service UUID, so no hostname, IP address, shared Wi-Fi, HTTP server, or port forwarding is involved. Other implementations can use the protocol in [`DEVICE_API.md`](./DEVICE_API.md).



Wi-Fi stays available for OpenGolfSim and internet traffic. Pi service 0.4.0 can scan and join a Wi-Fi network from the app's **Device → Wi-Fi setup** card. BLE pairing and Wi-Fi provisioning are proximity-only in this MVP; disable provisioning or add authenticated bonding before shared-space deployment.



## Connect to OpenGolfSim



Open the **Device** tab and use **Simulator connection**. Web mode connects directly using the OpenGolfSim account email. Desktop mode uses the included Expo-compatible WebSocket-to-TCP bridge; follow [`OPENGOLFSIM.md`](./OPENGOLFSIM.md) for setup.



## Project layout



```text

App.tsx                         App shell and tab navigation

src/components/                Reusable UI and shot visualizations

src/context/                   Device/demo state and reconnection logic

src/data/                      Interactive demo data

src/screens/                   Monitor, Putting, Calculator, Sessions, and Device screens

src/services/device.ts         Request/response and live-event BLE client

src/services/bleTransport.*    Native BLE adapter and web demo-only fallback

src/services/opengolfsim.ts    OpenGolfSim WebSocket client and shot mapping

bridge/                        OpenGolfSim Desktop TCP bridge

raspberry_pi/                  Installable Pi BLE peripheral, test backend, and systemd setup

src/theme.ts                   Design tokens

src/types.ts                   Shared API and app types

```



## Build targets



The app uses Expo SDK 54 with a custom development client because BLE requires native code. Android builds can be created locally on Windows or with EAS; iOS builds can be created by EAS without a Mac. The current app/build versions are `3.8.2`, iOS build `41`, and Android version code `41`. The home-screen name is **LM1**.



Quality targets for a mid-range phone are: first useful native screen within 1.5 seconds; web-preview LCP ≤ 2.0 seconds, INP ≤ 200 ms, and CLS ≤ 0.1 at p75; ≤ 220 KB gzip JavaScript for the single web route; Lighthouse performance ≥ 85 and accessibility ≥ 95. Accessibility ownership sits with the app team, targeting WCAG 2.1 AA-equivalent contrast, labels, and touch targets.

Pi service 0.26.0 supports saved ground-tag pose: explicitly capture AprilTag calibration after lens calibration, then remove the ground tag while keeping the camera, focus and hitting surface fixed. Reset empty plane clears ground pose and target line and requires the tag again. App 3.8.2 explains this flow.
