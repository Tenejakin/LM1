# LM1 above-camera IR bracket v1.3.0

This one-piece bridge places both IR emitters above the camera on the open LM1
v0.5.1 mast. It shares the two upper M3 camera-bracket screws, located 110 mm
apart, and does not require drilling or replacing the mast.

The emitter centres are 28 mm above the upper screws and 86 mm apart. Each
32 x 38 mm adhesive pad points 28 degrees downward to follow the current camera
pitch and 4.915 degrees inward. The nominal horizontal beam axes meet 500 mm in
front of the device. The camera opening remains clear beneath the two pads.

## Print and install

Print the STL with its broad, flat rear face on the bed. Use PETG, 0.16-0.20 mm
layers, four walls and 35-45% infill. The part has two 3.4 mm clearance holes.
It will probably require longer upper camera-mount screws; begin by checking
M3 x 16 mm or M3 x 20 mm hardware and ensure the nuts fully engage.

Viewed from the front, the horizontal bridge sits across the upper screw pair
and the two pads extend upward. Their top edges project farther forward than
their bottom edges; this is what aims the emitters downward. Centre each LED
emitter on its pad rather than centring the PCB.

Use thin high-temperature double-sided tape only on clear PCB areas. Keep
heatsinks, components, solder joints and wiring uncovered. The printed bracket
is not a heatsink. Power the IR modules off during alignment and stop using the
mount if the tape loosens or the plastic softens.

## Package

- `lm1-ir-top-bracket-v1.3.0.stl`: printable one-piece bridge.
- `preview.png`: installed concept; cream mast and black camera are references.
- `build-report.json`: dimensions and mesh validation.
- `build.py`: editable source requiring numpy, trimesh, manifold3d and Pillow.
- `lm1-ir-top-bracket-v1.3.0.zip`: complete printable package.

The exported mesh is checked as one connected watertight solid. Geometry uses
the v0.5.1 mast dimensions and the supplied photo. PCB size, screw-stack length,
camera field-of-view clearance and physical fit still require a test-fit.
