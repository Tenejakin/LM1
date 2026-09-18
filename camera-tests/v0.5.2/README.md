# Camera lighting configuration v0.5.2

2026-09-07: set the CSI stream to 640x400 at 200 fps with automatic exposure. The full-resolution mode cannot reach 200 fps. App remains 2.3.0 and service remains 0.5.0; only camera configuration changed.

First preview sensor metadata reported 200.4 fps, 2189 us exposure, gain 1.0. Service active with zero automatic restarts. This is sensor FrameDuration-derived rate, not an end-to-end processing throughput benchmark. Saved a fresh snapshot as 200fps.jpg.

Left 200 fps active for phone preview; BLE still refreshes every three seconds. Previous 90 fps environment is backed up at /var/lib/pinpoint/pre-200fps-v0.5.2.env. Sharpness scores are not comparable across resolution or scene changes.
