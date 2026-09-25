# LM1 dual-camera bracket — v0.5.3

This revision replaces the single-camera v0.5.2 bracket with one rigid carrier
for two camera boards. The camera optical centres are horizontal, share the same
15-degree downward pitch, and are 58 mm apart. A single carrier fixes the
relative camera pose, which is preferable to two independently flexing mounts
for stereo reconstruction or synchronized secondary-view measurements.

The four mast holes are unchanged, so the v0.5.3 bracket is a direct replacement
on the v0.5.2 tray and mast. Only
`lm1_test_dual_camera_bracket_15deg_v0.5.3.stl` needs to be printed when upgrading
an existing stand. Print it in the supplied orientation with 0.2 mm layers,
four walls, and 25–35% infill. Use a stiffer material such as PETG, ASA, or CF-PETG
when camera-to-camera calibration stability matters.

Each camera has its own 22 mm lens aperture and four diagonal slots supporting
nominal square mounting-hole patterns from 24 to 34 mm. Fit identical insulating
spacers under both PCBs and avoid overtightening one board more than the other.
Route the two CSI/USB cables separately down the open mast with a small service
loop and strain relief; cable tension must not twist the carrier.

The 58 mm baseline is a practical compromise for this 130 mm mast: the two
54 mm boards remain within the stand envelope, have a 4 mm nominal gap, and keep
their fasteners clear of the mast flanges. Both cameras intentionally share pitch
and height. Correct residual alignment in stereo calibration rather than bending
the mount.

After installation, verify that both lenses see the full ball flight region,
synchronize exposure and frame timing, calibrate intrinsics for each camera and
then calibrate their stereo/extrinsic relationship. Re-run the device ground-pose
and target-line calibration after any camera or bracket movement.
