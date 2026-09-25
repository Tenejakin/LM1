# LM1 performance stereo stand — v0.6.0

Version 0.6.0 is the performance-oriented replacement for the compact v0.5.3
retrofit. It uses a new tray, mast and rigid common camera carrier.

## Geometry and purpose

- Two parallel optical axes with a 120 mm horizontal baseline improve depth
  triangulation and provide a second view when the club occludes the ball.
- Both lens centres are 200 mm above the hitting surface and pitched 20 degrees
  downward. Their nominal optical axes meet the ground about 550 mm in front of
  the stand, matching the project's approximately 0.5 m working-distance model.
- Parallel mounting simplifies stereo rectification. Do not toe the cameras in;
  calibrate their residual relative pose in software.
- A 220 x 150 mm base, uprights at +/-95 mm, three cross ties and one-piece
  camera carrier resist roll, yaw and camera-to-camera twist.

The larger geometry intentionally does not fit the old mast. Print the tray,
mast and dual-camera bracket from `stl/v0.6.0-stereo`. Use 0.2 mm layers, at
least four walls and 30–40% infill. PETG, ASA or CF-PETG is recommended over PLA
where sunlight or heat could slowly alter calibration. Add steel ballast through
the tray slots or fasten the base to a rigid surface.

## Camera and cable setup

This mechanical design assumes two matching camera boards no larger than 54 x
54 mm with 24–34 mm square mounting patterns. Use identical rigid insulating
spacers. Route and strain-relieve each cable independently; neither cable may
load the PCB or carrier. A second camera only improves measurement if the pair
supports external hardware synchronization or demonstrably shared exposure
timing. Two unsynchronized rolling timestamps can create false 3D motion.

Before a real shot, confirm both cameras overlap across the resting ball and at
least the first 400 mm of flight. If the actual lens field of view or stand-to-ball
distance differs, treat 20 degrees as a prototype angle and verify framing before
printing multiples.

Calibrate each camera's intrinsics at its exact focus, crop and resolution, then
perform stereo/extrinsic calibration with the carrier fixed. Finally recalibrate
the ground pose and target line. Any fastener, focus, resolution or physical
position change invalidates the affected calibration.
