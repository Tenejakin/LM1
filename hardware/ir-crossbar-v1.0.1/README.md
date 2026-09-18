# IR tape-pad stand v1.0.1

Updated from the preliminary v1.0.0 zip-tie frames to two solid flat pads, as requested for double-sided tape.

Overall size: 120 x 28 x 42 mm. Each tape pad: 32 x 38 mm, 3 mm thick. LED optical centres should be 86 mm apart, aligned to the centre of each pad at 23 mm above the underside. Each pad turns inward 4.915 degrees. Nominal beam axes meet on the centreline 500 mm forward of the midpoint between LED centres, at the same height as those centres. This is aiming geometry, not optical focusing. Actual LED protrusion changes the intersection slightly. Tilt the entire stand if the ball sits lower than the LEDs.

The centre notch marks the forward side. Attach each board to the forward face of its pad, with the LED facing toward the notch/target. Keep boards parallel to their pads and centre the emitter, rather than the PCB. Board dimensions are not verified; boards may overhang the pads and the 120 mm outside limit applies to the printed part, not automatically to the attached boards. Measure the assembled outside width before use.

Use narrow strips of double-sided tape on clear PCB areas only. Do not cover the heatsink, contacts or components. These solid pads are unsuitable if they obstruct the board's heatsink; keep a gap or move attachment to clear edges. The plastic and tape do not replace LED cooling. Switch off LEDs before alignment and stop if tape loosens or plastic softens.

Print the broad 120 x 28 mm base flat on the bed. Suggested: PETG, 0.2 mm layers, 4 walls, 25% infill. The pads are vertical with straight walls; no window bridges or supports are needed. Two 3.4 mm base holes can take M3 fixings. Hardware and camera mounting are not included.

The STL is one connected watertight solid in millimetres. build-report.json records mesh checks and analytical beam-axis intersection. preview.png is rendered from that mesh. build.py is editable source, requiring numpy, trimesh, manifold3d and Pillow; run `python build.py` to regenerate. Fit, print tolerances, temperature and real beam shape require physical checking.
