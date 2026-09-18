# LM1 IR side brackets v1.2.0

These mirrored brackets move the two IR modules from below the camera to the
left and right sides of the open LM1 v0.5.1 mast. Each bracket uses the two
existing M3 holes in one upright (44 mm vertical spacing), so it can share the
camera-bracket bolts when fitted with longer screws.

The IR optical centres sit approximately 12 mm inward from the upright
centrelines. On the 110 mm upright spacing shown in the current mast, this puts
the LED centres 86 mm apart. Each 32 x 38 mm tape pad has an integrated
4.915-degree horizontal wedge that points the emitter slightly inward; the
nominal beam axes meet 500 mm in front of the device. Version 1.2.0 also pitches
both mounting faces 28 degrees downward to match the current v0.5.1 camera
bracket. The top of each pad therefore projects farther forward than the bottom.
This is aiming geometry, not optical focus, and the real beam pattern may need
a small physical adjustment.

## Print and fit

Print one left and one right STL with the broad flat rear face on the bed. Use
PETG, 0.16-0.20 mm layers, four walls and 35-45% infill. The model includes
3.4 mm clearance holes for M3 hardware. Start with M3 x 16 mm screws if the
part shares the existing camera-bracket stack, but verify the required length
and ensure the nut has full thread engagement.

Attach each IR board to the sloped forward face using thin high-temperature
double-sided tape on clear PCB areas. Centre the emitter on the pad rather than
centering the PCB. Keep the LED heatsink, components, solder joints and wiring
uncovered. The plastic bracket is not a heatsink. Power the emitters off while
aligning and stop using the mount if tape loosens or the plastic softens.

The front face gets thicker toward the outside of each bracket. Therefore the
left and right files are not interchangeable. Viewed from the front of the
device, install `left` on the viewer's left and `right` on the viewer's right.

## Files and validation

- `lm1-ir-side-bracket-left-v1.2.0.stl` and `...right...`: printable parts.
- `preview.png`: assembly concept; cream mast and black camera are references.
- `build-report.json`: dimensions and mesh checks.
- `build.py`: editable source; requires numpy, trimesh, manifold3d and Pillow.
- `lm1-ir-side-bracket-v1.2.0.zip`: complete printable package.

The meshes are checked as single connected watertight solids. Dimensions were
derived from the v0.5.1 CAD and the supplied photo, but the IR PCB footprint,
screw stack and physical clearances have not yet been measured on the actual
device. Test-fit before a long unattended run.
