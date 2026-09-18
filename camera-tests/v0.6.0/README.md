# Ball detection overlay v0.6.0

App 2.4.0/build 14, Pi service 0.6.0, BLE protocol 2.4.0.

Deployed to lm1@192.168.0.140 on 2026-09-07. Camera remains 640x400 at sensor-reported 200.4 fps. Detection enabled with stride 20, calibration 30 samples, present debounce 8 samples, absent debounce 5 samples.

Verified live service starts, produces a real preview with ballDetection=calibrating, and completes background calibration. Zero automatic restarts. iOS bundle, TypeScript, lint and simulator bridge check passed. Phone preview transport was confirmed by the user in the preceding version; physical ball placement and the new phone overlay still require user observation.

Preview metadata carries the detector state and normalized bounds of the accompanying image. The app displays calibration/waiting/detected/disabled labels, draws bounds, and suppresses detected claims after ten seconds without a preview or on disconnect. Independent from manually armed shot state.

Keep the green region empty during startup calibration; place a ball in it afterward. Camera movement requires fresh empty-background calibration. Shot results remain synthetic.

Previous Pi code and environment backed up at /var/lib/pinpoint/pre-ball-0.6.0. Deployment sources: /home/lm1/lm1-ball-0.6.0.
