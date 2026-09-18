# LM1 CSI integration verification v0.5.0

Tested 2026-09-07 on the existing LM1 Pi: `lm1@192.168.0.140` (`raspberrypi.local`). SSH uses the existing `~/.ssh/lm1_codex_ed25519` key on the Windows host. Camera: OV9281 on CAM0.

- Pi service 0.5.0 / BLE protocol 2.3.0 deployed and enabled; zero automatic restarts at verification.
- App 2.3.0 / build 13; TypeScript, lint, iOS bundle and simulator bridge check passed.
- All 29 Python tests passed on the Pi, including OpenCV tests.
- Picamera2 captured 1280x800 at a sensor-reported 30 fps. Automatic exposure settled around 10 ms at gain 1.
- Service produced a 1275-byte BLE JPEG and live diagnostics including focus score 50.8 in the current room scene. This is a relative score, not a focus calibration.
- `/var/lib/pinpoint/camera-latest.jpg` updates about every three seconds from the service-owned stream. `focus-latest.jpg` here is a saved snapshot, not a live feed.
- Autofocus control is unavailable. Optical focus is adjusted at the lens with a target at ball distance.
- Automatic ball detection is disabled during focus setup; shot metrics remain synthetic.
- The Windows BLE scan did not find LM1. Phone-side preview reception remains unverified.

Boot configuration backup: `/boot/firmware/config.txt.pre-lm1-camera-v0.1.0`.
Previous service Python files and environment/systemd configuration: `/var/lib/pinpoint/pre-csi-0.5.0` (root only).
Deployment sources: `/home/lm1/lm1-csi-0.5.0`.
Phone development server: `http://192.168.0.199:8081`.
