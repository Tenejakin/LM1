# LM1 15-degree camera bracket — v0.5.2

This revision changes the open test stand camera pitch from 28 degrees to
15 degrees downward. The mast bolt pattern and diagonal camera-board slots are
unchanged, so the bracket is a direct replacement for the v0.5.1 bracket.

Print `lm1_test_camera_bracket_15deg_v0.5.2.stl` in the supplied orientation
with 0.2 mm layers, four walls and 20–25% infill. Reuse the existing four mast
fasteners and camera hardware. Install the bracket with the lens facing through
the open mast frame and the top of the camera tipped toward the rear.

The diagonal slots support nominal square camera-hole patterns from 24 to
34 mm. Use insulating spacers between the camera PCB and printed bracket, and
leave enough ribbon-cable slack to avoid pulling the camera out of alignment.

To regenerate all v0.5.2 test-stand files, keep `lm1_case_v0_2_0.py` beside
`lm1_test_v0_5_2.py`, install the packages in `requirements-cad.txt`, and run:

```powershell
python lm1_test_v0_5_2.py
```
