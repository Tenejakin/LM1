# Simple IR triangular wedge v1.0.2

Replaces the full stand with just a triangular wedge for attaching to the existing bracket, as requested.

Size: 32 x 38 mm footprint, rising from zero to 2.752 mm. Angle: 4.915 degrees between flat back and sloping board face. Print two copies; rotate the second 180 degrees on its mounting face to reverse the tilt. No holes, frame or stand included.

Print flat-face down at 100% scale in millimetres, preferably PETG with 0.12-0.16 mm layers and solid infill. The thin tip may lose a fraction of a millimetre during slicing; do not place supports under the slope. Tape the flat face to the existing bracket and the board to the sloping face. Equal tape thickness across each face preserves the angle. Keep heatsinks and components clear, and do not rely on tape or plastic for LED cooling.

On a bracket initially parallel to the LED baseline, orient the wedges so both LED axes turn inward. Angle alone does not fix crossing distance: 4.915 degrees intersects 500 mm ahead only at 86 mm LED optical-centre spacing. At 120 mm optical-centre spacing it intersects about 698 mm ahead. Any existing bracket angle adds to the wedge angle. Set LED centres at 86 mm if the existing mount is straight and you want the nominal 500 mm crossing. Beam shape and actual LED protrusion affect real illumination.

Mesh checked as a single watertight solid; angle checked from the triangular section. Board footprint, mounting heat and physical fit remain unverified. Source requires numpy and trimesh.
