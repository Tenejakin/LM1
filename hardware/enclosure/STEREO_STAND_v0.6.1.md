# LM1 modular stereo stand — v0.6.1

This revision fits a 180 x 180 mm print bed. The mast is divided into lower and
upper rigid frames, joined at 120 mm by four printed splice plates: one on the
front and rear of each upright. Use eight M4 x 25 mm bolts, washers and locknuts.
The joint is deliberately below the cameras and uses both faces of each upright
to resist pitch and yaw.

The carrier baseline is 90 mm instead of v0.6.0's 120 mm so the one-piece camera
carrier remains printable and calibration-stable. Lens centres remain 200 mm high
at 20 degrees downward, intersecting the ground about 550 mm ahead. The 176 x
150 mm tray, 174 mm mast frames and 170 mm carrier all fit the target bed.

Print one tray, lower mast, upper mast and camera carrier, plus four copies of the
splice plate. Use PETG, ASA or CF-PETG, 0.2 mm layers, at least five walls around
the mast and splice plates, and 35–45% infill. Assemble on a flat surface, tighten
both sides evenly, then check that the upper frame cannot twist before calibrating.

Use identical externally synchronized global-shutter cameras, equal spacers and
independent cable strain relief. Calibrate each lens, then stereo extrinsics,
ground pose and target line only after final assembly. Retightening a joint or
moving a camera invalidates extrinsic calibration.
