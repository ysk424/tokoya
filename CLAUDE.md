# Tokoya Development Notes

Status: public release.

Tokoya is the hair-generation and grooming half of the Tokoya + Yurameki
workflow. Tokoya creates, settles, cuts, and resets long straight hair. Yurameki
simulates the groomed Curves object.

## Current Release

- Version: 0.9.0.
- Tested workflow target: Blender 5.2 beta.
- Platform target: Windows x64 and macOS arm64.
- License: MIT.
- Release package: `dist/tokoya-0.9.0.zip`.

## Current Direction

- Keep Tokoya focused on mask planting, initial long-hair grooming, cutting, and
  reset.
- Keep simulation playback and final dynamic hair motion in Yurameki.
- Avoid destabilizing the existing settle and cutting workflow while preparing
  the public release.

## Important Behavior

- `Create Head Mask` creates a paint mesh outside the Body surface.
- `Plant Hair` reads grayscale mask pixels:
  - white means 0 cm hair,
  - black means maximum length,
  - gray means interpolated length.
- `Plant Z-axe` reads the same mask, but places roots on constant-world-Z
  contour lines instead of scattering them. Every strand of one row shares one
  Z value. Row Z levels are not uniform: the painted area between two rows is
  held at `contour length * spacing`, so surface spacing is even along a row and
  between rows. `Strands` is a target, not an exact count.
- `Max Length` determines the shared point count for all strands.
- Natural Root Spacing keeps the first two root-side segments aligned to the
  maximum-length strand when possible.
- `Settle Hair Back` and `Settle With Guide` are initial grooming tools, not
  final dynamic simulation tools.
- Body collision during settle uses a filled Body Collider Proxy.
- Hair-hair collision is not implemented.

## Collision And Solver Pitfalls

- Do not add hair-hair collision without a measured design. It is expensive and
  can destabilize long straight hair.
- Collision work must use evaluated world-space coordinates when Surface Deform
  or armature deformation is involved.
- Cutting and settling must write back through the evaluated/original offset so
  modifier-driven display positions remain consistent.
- Collider proxy changes must be validated on eye, ear, and scalp boundary
  regions.
- Avoid speculative optimization. Measure before changing collision or grooming
  behavior.

## Release Notes

### 0.9.0

- Added `Plant Z-axe` next to `Plant Hair`; the two now share one button row.
- Roots are snapped onto the slicing plane, so one row is bit-equal in Z rather
  than equal only to float precision.
- Z-sliced strands carry the `tokoya_z_row`, `tokoya_z_strip` and
  `tokoya_z_order` INT curve attributes so a later XPBD pass can build
  horizontal constraints between row neighbours. Neighbours are consecutive
  `tokoya_z_order` values inside the same `tokoya_z_strip`; a strip is one
  unbroken contour, so strips must not be joined across a gap.
- The Curves object gets `tokoya_plant_mode = "Z_SLICE"`, `tokoya_z_rows` and
  `tokoya_z_spacing_m`.

### 0.8.0

- Added a `Prepare for ZOZO` hand-off, mirroring the Yohsai ZOZO button.
- The groomed Hair Curves become a solver-owned ROD (edge-only) mesh, one
  polyline per strand, baked from evaluated world coordinates.
- The Body is duplicated with its modifiers as a STATIC collider so ZOZO can
  capture its deformation.
- A child process configures ZOZO Contact Solver over its MCP server on port
  9633 (`create_group` ROD/STATIC, material properties, scene parameters), and a
  timer reports progress in the panel's ZOZO status line.
- Tokoya's own Curves, Body and scene stay untouched; re-preparing the same hair
  reuses and clears its `<hair>_ZOZO` collection.

### 0.6.9

- Public README and manifest text are English.
- UI labels are held in English even when Blender's UI language is Japanese.
- Release documentation now describes the Tokoya + Yurameki workflow.

### 0.6.8

- `Settle With Guide` switched from temporary mesh collision to a numeric Back
  Flow Guide.

### 0.6.7

- Back Flow Guide was extended behind and below the shoulders.
- Settle button layout was cleaned up.

### 0.6.6

- `Settle With Guide` used a temporary Back Flow Guide instead of a sphere.

### 0.6.5

- Temporary bang cutters and settle Collider Proxy objects were removed after
  processing.

### 0.6.4

- `Trim Bangs` added automatic cutter creation near the eye region.

### 0.6.3

- `Settle Hair Back` was moved to evaluated display coordinates for Surface
  Deform compatibility.

### 0.6.2

- The old `Simulate` button was replaced by `Settle Hair Back`.

### 0.6.0

- Long-hair point count became length-dependent.
- Natural Root Spacing was introduced.
- Hair recording features were removed from Tokoya and left to the separate
  simulation path.

## Testing

Minimum checks before release:

```powershell
python -m py_compile .\__init__.py .\ui.py .\_world_passthrough.py .\_collision_warp.py .\_sim_warp.py .\_sim_taichi.py .\_mask_plant.py .\_mesh_ops.py .\_initial_groom.py .\_collider_proxy.py .\_zozo_handoff.py .\_zozo_mcp_client.py
```

Manual Blender validation should cover:

- mask creation,
- hair planting,
- `Plant Z-axe` (flat rows, even spacing, no bald seam at the mask border),
- `Settle Hair Back`,
- `Settle With Guide`,
- `Mesh Shrink`,
- `Trim Bangs`,
- `Urchin Reset`,
- `Prepare for ZOZO` (rod + body copies, ZOZO MCP on :9633),
- handoff to Yurameki.
