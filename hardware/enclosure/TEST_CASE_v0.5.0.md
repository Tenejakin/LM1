# LM1 camera test case — v0.5.0

A three-piece open prototype for Pi 5 and camera setup. Print one tray, one
mast, and one camera bracket. No display or LED modules are required.

The footprint is 140 x 130 mm; assembled height is 184 mm. The nominal camera
board centre is 150 mm high with a 13-degree downward pitch. Actual lens-centre
height depends on lens projection and module construction. Add foot thickness
to all height measurements. Check framing before calibration.

## Assembly

1. Bolt the mast foot onto the tray with four M3 x 10 mm screws, nuts and washers.
   Screw heads enter the recessed underside holes. A shim/washer may be needed
   depending on the screw-head profile.
2. Bolt the camera bracket to the rear of the mast at its four matching holes
   with M3 x 12 mm screws and nuts. Lens looks through the open frame toward the
   short front edge of the tray. Both sides of these screws remain accessible.
3. Mount Pi 5 on the four tray bosses using M2.5 x 16 mm through-bolts and nuts.
   Holes are 2.8 mm clearance diameter. Add feet at least 4 mm thick to clear
   the underside nuts, or mount on a board with clearance pockets. Do not force
   the PCB down. Board outline is 85 x 56 mm and hole spacing is 58 x 49 mm.
4. Mount the camera with insulating spacers so solder joints cannot touch the
   bracket. Its diagonal slots span square hole patterns from 24 to 34 mm.
   Exact OV9281 module dimensions still need confirming. A USB webcam needs its
   own adapter; this bracket is intended for the planned board camera.
5. Route a sufficiently long CSI cable down through the open mast, with slack
   and no tight folds. All Pi ports and the active cooler remain accessible.

## Printing and use

STLs are millimetres and already oriented: tray flat, mast and bracket with
their broad faces parallel to the bed. They may need local supports under overhangs; inspect
the slicer preview. Use 0.2 mm layers, four walls and 20–25% infill. The longest
part is 180 mm. Test a fastener hole before committing to all parts.

This open stand is for dry bench/framing tests. It does not shield the electronics
from a golf-ball strike or rain. Secure it to a board or add ballast through the
tray slots before swing capture, and use a separate protective barrier outside
the camera view. There is no protective window included in this simple revision.

`assembly_reference` is for viewing, not a print job. Print the three named
parts separately. The green Pi and grey cooler in the preview are placeholders.

## Regeneration

Keep the included `lm1_case_v0_2_0.py` beside `lm1_test_v0_5_0.py`; it supplies
shared mesh primitives and the camera bracket. Install numpy, trimesh,
manifold3d and Pillow, then run `python lm1_test_v0_5_0.py`.

Mesh checks cover closed surfaces, positive volume and a single connected
solid for each exported printable STL. No physical print or hardware fit test
has been performed.
