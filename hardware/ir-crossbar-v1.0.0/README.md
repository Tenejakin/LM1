# IR crossbar prototype v1.0.0

One-piece stand for two DollaTek Raspberry Pi camera IR boards. Actual PCB dimensions and fit are not verified. Do not print as a final fitted board mount until the board is measured.

The entire part is 120 x 28 x 42 mm. Nominal LED centres are 86 mm apart, each aimed inward by atan(43/500) = 4.915 degrees. With LED centres aligned to the frame centres and the boards parallel to their frames, beam axes intersect 500 mm forward of the centre between the LEDs, at the same height. The base's centre notch marks the forward edge. The distance is measured perpendicular to the LED baseline, not along either angled beam. LED protrusion shifts the actual intersection distance slightly.

This changes aiming only; it does not concentrate or increase optical power. Tilt the whole stand if the ball is below the LEDs. The target must lie on the stand's centreline.

## Board attachment

Each upright frame is 32 mm wide x 38 mm high, with a 24 x 28 mm open window. Four 1.8 x 6 mm slots allow small zip ties. Seat the PCB rear against the forward face of the frame, with the emitter facing the centre notch. Align the LED optical centre with the frame centre (23 mm above the base underside), even if that is not the PCB centre. Retain only clear PCB edges with nonconductive ties; do not press on components, bare contacts, wiring or hot heatsinks. The open window must leave the heatsink and components clear. If the actual PCB does not span the opening or its emitter cannot be aligned, stop and revise dimensions in build.py. This is a universal prototype, not a claimed exact DollaTek fit.

Two 3.4 mm base holes accept M3 fixings to a separate stand (22 mm each side of centre, 7 mm toward the target). No camera attachment geometry is included.

## Print

Print with the broad base flat on the bed, 0.2 mm layers, 4 walls and approximately 25% infill. The two window tops bridge 24 mm; inspect your slicer preview and use removable supports if your printer cannot bridge this span. PETG is preferable near warm equipment, but plastic must not serve as the LEDs' heatsink. Power off the IR while aligning. Keep the original heatsinks exposed and stop if the mount softens.

## Files and validation

- ir-crossbar-v1.0.0.stl: printable single connected solid, millimetres.
- preview.png: orthographic view generated from its mesh.
- build-report.json: watertightness, dimensions and aiming check.
- build.py: editable source; Python with numpy, trimesh, manifold3d and Pillow.

Run `python build.py` to regenerate. Angle derives from SPACING and TARGET_DISTANCE. Changing spacing also requires checking frame clearance and overall width. Nominal axes are analytically checked to intersect at [0, 500, 23] mm. Mesh checks do not validate physical PCB fit, print tolerances or beam shape.
