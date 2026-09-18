# Camera lighting configuration v0.5.1

2026-09-07: switched the running CSI service to 90 fps at 1280x800 with automatic exposure. App remains 2.3.0 and service remains 0.5.0; this is a camera configuration change.

First preview sensor metadata: 90.1 fps, 4427 us exposure, gain 1.0. Service active with zero automatic restarts. Fresh full-resolution snapshot saved as 90fps.jpg; the scene is visible with dark background areas. Camera position differs from the earlier 30 fps snapshot, so these images are not a controlled brightness comparison.

Left 90 fps active for phone preview. Previous environment backed up on the Pi at /var/lib/pinpoint/pre-90fps-v0.5.1.env. BLE preview still refreshes every three seconds. User confirmed phone preview reception before this test.
