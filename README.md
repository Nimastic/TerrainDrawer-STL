# Draw-on-STL Terrain Route Souvenir

Create a 3D-printable terrain souvenir from an STL terrain model and a hiking route.

This tool lets you:
- load a terrain STL
- draw or reuse route points on a top-down terrain view
- smooth the route into a clean curve
- generate a raised route overlay on top of the terrain
- export separate files for terrain, route, combined geometry, and color previews

This is useful for mountain trek souvenirs, summit routes, Strava path overlays, and multi-color 3D printing workflows.

---

## What gets exported

After a successful run, the script exports:

- `terrain_solid.stl`  
  The printable terrain with a flat base.

- `route_overlay_only.stl`  
  The raised route overlay as a separate printable part.

- `terrain_with_route_combined.stl`  
  Terrain and route merged into one STL.

- `terrain_with_orange_route_preview.glb`  
  Color preview of terrain + orange route.

- `route_overlay_only_orange_preview.glb`  
  Color preview of the route only.

- `route_preview.png`  
  Top-down preview of the terrain with the selected route points.

- `route_points.json`  
  Saved route control points for reuse/editing.

---

## Install

Use Python 3.10+ or 3.11.

Install dependencies:

```bash
python -m pip install trimesh numpy scipy matplotlib
```

---

## Input files

You need:

- a terrain STL, for example:
  - `tsorku_peak_terrain_solid_base_5mm.stl`
- optionally, an existing route JSON:
  - `route_points.json`

If you do not already have route points, the script can open an interactive window so you can click the path manually.

---

## Workflow overview

### 1. Start from the terrain STL

Make sure your terrain STL is already a printable solid with a flat base.

If your original STL was only a floating terrain surface, convert it into a solid terrain block first before using the route tool.

### 2. Create route points

You have two options:

#### Option A — draw points interactively
Run the script without `--points-json`.

```bash
python draw_route_on_terrain.py \
  --input tsorku_peak_terrain_solid_base_5mm.stl \
  --output-dir output \
  --flip-y
```

A terrain window opens.

Controls:
- left click = add route point
- `U` or `Backspace` = undo last point
- `C` = clear all points
- `Enter` = export
- `Esc` = quit without exporting

This creates `route_points.json`, which stores the clicked route points.

#### Option B — reuse an existing route JSON
If you already have `route_points.json`, pass it in with `--points-json`.

This is the normal workflow after your first successful route edit.

### 3. Edit the route points if needed

If the path needs adjusting:
- edit `route_points.json` manually in VS Code, or
- use your separate `edit_route_points.py` helper to reload the route and refine the points visually

Then rerun `draw_route_on_terrain.py` with the edited JSON.

### 4. Smooth the route

The route points are converted into a smoothed spline before the overlay mesh is built.

Relevant settings:
- `--sample-step` controls how densely the smoothed curve is sampled
- `--smoothing` controls how much the curve is smoothed
- `--no-smooth` disables spline smoothing and keeps the route more polyline-like

### 5. Generate the route overlay

The script builds a continuous raised ribbon following the route.

Relevant settings:
- `--route-width` controls the route thickness across the terrain surface
- `--route-height` controls how tall the route sits above the terrain
- `--terrain-overlap` slightly sinks the route into the terrain so it fuses cleanly for printing

### 6. Export outputs

The script exports separate terrain, route, and combined files.

### 7. Prepare for printing

For single-color printing:
- print `terrain_with_route_combined.stl`
- or print the terrain and paint the route afterward

For multi-color printing:
- load `terrain_solid.stl`
- load `route_overlay_only.stl`
- combine them as parts of the same model in your slicer
- assign a different filament color to the route part

---

## Example command

Use this as a reference command:

```bash
python draw_route_on_terrain.py \
  --input tsorku_peak_terrain_solid_base_5mm.stl \
  --points-json route_points.json \
  --output-dir output \
  --flip-y \
  --route-width 0.8 \
  --route-height 0.5 \
  --terrain-overlap 0.05 \
  --sample-step 0.3 \
  --smoothing 0.5
```

Notes:
- `--flip-y` is useful when the displayed terrain view matches your expected route orientation only after a Y flip.
- `--route-width 0.8` makes the route relatively thin.
- `--route-height 0.5` makes it visible without becoming too bulky.
- `--terrain-overlap 0.05` helps the route attach to the terrain.
- `--sample-step 0.3` gives a smoother continuous route.
- `--smoothing 0.5` softens the clicked point path into a cleaner curve.

---

## Recommended settings

### Small souvenir print
For a print under about 10 cm wide:

```bash
--route-width 0.8
--route-height 0.5
--terrain-overlap 0.05
--sample-step 0.3
--smoothing 0.5
```

### Thinner route
If the route covers the summit too much:

```bash
--route-width 0.6
--route-height 0.4
```

### More visible route
If the route is hard to see:

```bash
--route-width 1.0
--route-height 0.6
```

---

## Understanding the output files

### `terrain_solid.stl`
Use this when you want only the terrain.

### `route_overlay_only.stl`
Use this as a separate printable body for multi-color printing.

### `terrain_with_route_combined.stl`
Use this when you want a one-piece print.

### `.glb` files
These are preview files.
They can show color.

### `.stl` files
STL is generally geometry-only.
Do not expect STL viewers to preserve or display orange route color.
If the STL looks white or gray, that is normal.

---

## Multi-color printing workflow

If you want the route in orange and the terrain in another color:

1. Open your slicer, for example:
   - Bambu Studio
   - OrcaSlicer
   - PrusaSlicer

2. Import:
   - `terrain_solid.stl`
   - `route_overlay_only.stl`

3. Make sure they are loaded as parts of the same model.

4. Do **not** auto-center them separately.

5. Assign:
   - terrain = base color filament
   - route = orange filament

6. Slice and print using multi-material or multi-color support.

If you do not have a multi-color printer:
- print the combined model and paint the route afterward, or
- print terrain and route separately and glue/paint as needed

---

## Cropping an exported terrain STL

If you want to trim the terrain after export, use `crop_terrain_stl.py`.

What it does:
- removes a fraction from the positive X side of `terrain_solid.stl`
- rebuilds the terrain as a watertight solid
- closes the cut face so the cropped side is capped, not exposed
- preserves the original flat base thickness

This helper is dependency-free and works directly on the exported binary STL.

### Example: remove the rightmost 10%

```bash
python3 crop_terrain_stl.py \
  --input output/terrain_solid.stl \
  --output output/terrain_solid_cropped_right_10pct_capped.stl \
  --crop-right-fraction 0.1
```

This writes a new cropped STL and keeps the original file unchanged.

### Replace the terrain STL in place

If you want the cropped file to become your main terrain STL:

```bash
cp output/terrain_solid_cropped_right_10pct_capped.stl output/terrain_solid.stl
```

### Rebuild the combined STL after cropping

If your route overlay still lies fully inside the kept terrain area, rebuild the combined STL with:

```bash
python3 merge_binary_stl.py \
  --output output/terrain_with_route_combined.stl \
  output/terrain_solid.stl \
  output/route_overlay_only.stl
```

`merge_binary_stl.py` simply merges multiple binary STL files into one binary STL.

### Important note about the route overlay

If `route_overlay_only.stl` extends into the part of the terrain you removed, do not merge it unchanged.

In that case, either:
- rerun `draw_route_on_terrain.py` from the source terrain and route points, or
- crop the route mesh separately before rebuilding the combined STL

### Useful crop values

```bash
--crop-right-fraction 0.05   # remove 5% from the right side
--crop-right-fraction 0.10   # remove 10% from the right side
--crop-right-fraction 0.20   # remove 20% from the right side
```

---

## Troubleshooting

### The route looks mirrored or upside down
Try:

```bash
--flip-x
```

or

```bash
--flip-y
```

Depending on how your terrain coordinates map to the displayed image.

### The exported STL looks white instead of orange
That is normal.
STL does not reliably store display color.
Use the `.glb` preview files for color visualization.

### The route looks too thick
Lower:

```bash
--route-width
--route-height
```

A good starting point is:

```bash
--route-width 0.8
--route-height 0.5
```

### The route covers the summit
Use a thinner route:

```bash
--route-width 0.6
--route-height 0.4
```

### The route looks jagged
Reduce sample step and/or increase smoothing:

```bash
--sample-step 0.2
--smoothing 0.8
```

### The shell command fails unexpectedly
Make sure there are **no spaces after the backslash** `\` in multiline shell commands.

Correct:

```bash
python draw_route_on_terrain.py \
  --input tsorku_peak_terrain_solid_base_5mm.stl \
  --points-json route_points.json \
  --output-dir output
```

Incorrect:

```bash
python draw_route_on_terrain.py \  
```

---

## Suggested end-to-end workflow

1. Prepare the terrain STL as a printable solid with a flat base.
2. Run the script interactively to create route points.
3. Save `route_points.json`.
4. Edit `route_points.json` if needed.
5. Rerun the script using the saved JSON.
6. Inspect:
   - `route_preview.png`
   - `terrain_with_orange_route_preview.glb`
7. Optionally crop `terrain_solid.stl` and rebuild `terrain_with_route_combined.stl`.
8. For one-color printing, print `terrain_with_route_combined.stl`.
9. For multi-color printing, load:
   - `terrain_solid.stl`
   - `route_overlay_only.stl`
   into your slicer as one assembled model.
10. Assign the route to orange filament.
11. Slice and print.

---

## Final note

For printing, the most important output files are usually:
- `terrain_with_route_combined.stl` for single-piece prints
- `terrain_solid.stl` + `route_overlay_only.stl` for multi-color prints

For visual checks, use:
- `terrain_with_orange_route_preview.glb`
- `route_overlay_only_orange_preview.glb`
