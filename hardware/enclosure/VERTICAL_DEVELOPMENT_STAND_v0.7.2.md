# LM1 vertical development stand — v0.7.2

Version 0.7.2 is a printable fit prototype for the two-camera LM1 development
hardware. It replaces the horizontal stereo carrier with two parallel cameras
on an 85 mm vertical baseline. The lower lens centre is 162.5 mm above the
hitting surface and the upper lens centre is 247.5 mm. Both are pitched 18
degrees downward.

## Architecture

- The lower camera is the primary impact camera and receives the 42-LED ring.
- The upper camera supplies the synchronized second view.
- Two 20 mm light-lens openings sit left and right of the lower camera.
- The Raspberry Pi 5 mounts immediately behind the optical carrier so both
  150 mm CSI ribbons stay in the head.
- The 150 x 65 x 30 mm power pack lies crosswise at the rear of the base,
  completely behind both mast feet and their mounting bolts.
- The provisional LiPo box lies front-centre between the mast uprights.
- The mast is split and reinforced with four splice plates so every printable
  part fits a 180 x 180 mm bed.
- The camera/light plate is completely flat and prints face-down without
  supports. Two small triangular rails create the 18-degree optical pitch and
  should also be printed on their broad sides without supports.
- The power pack, LiPo, camera boards, Pi, IR ring and side lights each have
  separate printable protective boxes, covers or shrouds.

## Important provisional dimensions

This is deliberately a development-fit version, not a final protective product.
The camera carrier supports boards up to 54 mm square and mounting patterns from
24–34 mm. The ring retainer assumes an 80 mm outer diameter and 32 mm centre
opening. The side-light apertures assume 20 mm lenses. Measure the real parts
before committing to a long or expensive print.

The ring carrier includes four strap slots to tolerate a modest diameter
difference. Do not drill the camera carrier while cameras are fitted: a changed
camera pose invalidates stereo calibration.

## Print list

- 1 × `lm1_vertical_base_v0.7.2.stl`
- 1 × `lm1_vertical_mast_lower_v0.7.2.stl`
- 1 × `lm1_vertical_mast_upper_v0.7.2.stl`
- 1 × `lm1_vertical_camera_light_carrier_v0.7.2.stl`
- 2 × `lm1_camera_tilt_rail_18deg_v0.7.2.stl`
- 4 × `lm1_mast_splice_plate_v0.7.2.stl`
- 1 × `lm1_ir_ring_retainer_80mm_v0.7.2.stl`
- 1 × `lm1_ir_ring_shroud_80mm_v0.7.2.stl`
- 1 × `lm1_pi5_head_cradle_v0.7.2.stl`
- 1 × `lm1_pi5_cover_v0.7.2.stl`
- 2 × `lm1_camera_board_cover_v0.7.2.stl`
- 2 × `lm1_side_light_pod_20mm_v0.7.2.stl`
- 1 × `lm1_power_pack_box_v0.7.2.stl`
- 1 × `lm1_power_pack_lid_v0.7.2.stl`
- 1 × `lm1_lipo_box_provisional_v0.7.2.stl`
- 1 × `lm1_lipo_lid_provisional_v0.7.2.stl`

Use PETG for the fit prototype and ASA or CF-PETG after the geometry is proven.
Suggested settings are 0.2 mm layers, five walls around the mast and carrier,
and 35–45% infill. Use washers and locknuts at the mast splice.

## Safety and validation

- Use constant-current LED drivers and metal heatsinks for the two 3 W emitters.
- Confirm the IR ring voltage, current and heat load before installing it.
- IR can be an eye hazard even when it looks dim; test at reduced power.
- Secure the LiPo without crushing or piercing it and use a fuse/BMS appropriate
  to the actual pack.
- Use a replaceable polycarbonate shield before hitting real golf balls.
- Externally synchronize both cameras. Two unsynchronized streams do not form a
  valid high-speed stereo measurement pair.
- Recalibrate both lenses, stereo extrinsics, ground pose and target line after
  final assembly or any fastener movement.

Regenerate the files with:

```powershell
python hardware/enclosure/lm1_development_v0_7_2.py
```
