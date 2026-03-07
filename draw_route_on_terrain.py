#!/usr/bin/env python3
"""
Interactive terrain route drawer for STL terrain souvenirs.

What it does:
1. Loads a terrain STL.
2. Builds a regular height grid from the mesh.
3. Lets you click a route on a top-down terrain map.
4. Projects the route onto the terrain surface.
5. Creates a raised route ridge suitable for 3D printing.
6. Creates a solid terrain block with a flat base.
7. Exports STL/GLB/PNG artifacts.

Typical usage:
    python draw_route_on_terrain.py --input terrain.stl --output-dir out

Controls in the drawing window:
- Left click: add a route point
- U or Backspace: undo last point
- C: clear all points
- Enter: finish and export
- Esc: quit without exporting
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import trimesh
from matplotlib.lines import Line2D
from scipy.interpolate import RegularGridInterpolator, splprep, splev

@dataclass
class TerrainGrid:
    x_values: np.ndarray
    y_values: np.ndarray
    z_grid: np.ndarray
    plane_axis_names: Tuple[str, str] = ('x', 'y')
    height_axis_name: str = 'z'

    @property
    def z_min(self) -> float:
        return float(np.min(self.z_grid))

    @property
    def z_max(self) -> float:
        return float(np.max(self.z_grid))

    @property
    def x_min(self) -> float:
        return float(self.x_values[0])

    @property
    def x_max(self) -> float:
        return float(self.x_values[-1])

    @property
    def y_min(self) -> float:
        return float(self.y_values[0])

    @property
    def y_max(self) -> float:
        return float(self.y_values[-1])

    @property
    def extent(self) -> Tuple[float, float, float, float]:
        return self.x_min, self.x_max, self.y_min, self.y_max




def cleanup_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Lightweight cleanup that stays fast on medium-size terrain meshes."""
    try:
        mesh.remove_unreferenced_vertices()
    except Exception:
        pass
    try:
        mesh.fix_normals()
    except Exception:
        pass
    return mesh


class HeightfieldInterpolator:
    def __init__(self, grid: TerrainGrid):
        self.grid = grid
        self._interpolator = RegularGridInterpolator(
            (grid.x_values, grid.y_values),
            grid.z_grid,
            bounds_error=False,
            fill_value=np.nan,
        )

    def z_at(self, x: float, y: float) -> float:
        value = self._interpolator(np.array([[x, y]], dtype=float))[0]
        if np.isnan(value):
            raise ValueError(f"Point ({x:.3f}, {y:.3f}) lies outside terrain bounds")
        return float(value)

    def many(self, xy_points: np.ndarray) -> np.ndarray:
        values = self._interpolator(np.asarray(xy_points, dtype=float))
        if np.isnan(values).any():
            raise ValueError("Some sampled route points lie outside terrain bounds")
        return np.asarray(values, dtype=float)


def load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load_mesh(path, force='mesh')
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Expected a mesh, got: {type(mesh)}")
    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ValueError("The STL appears to be empty")
    return mesh


def build_height_grid(mesh: trimesh.Trimesh, rounding_decimals: int = 6) -> TerrainGrid:
    """
    Convert a terrain mesh into a regular height grid.

    The function automatically detects which axis behaves like height and which
    two axes form the regular terrain plane.
    """
    vertices = np.asarray(mesh.vertices, dtype=float)
    axis_names = ['x', 'y', 'z']

    best = None
    for height_axis in range(3):
        plane_axes = [axis for axis in range(3) if axis != height_axis]
        a_vals = np.round(vertices[:, plane_axes[0]], rounding_decimals)
        b_vals = np.round(vertices[:, plane_axes[1]], rounding_decimals)
        h_vals = vertices[:, height_axis]

        a_unique = np.unique(a_vals)
        b_unique = np.unique(b_vals)
        a_index = {value: idx for idx, value in enumerate(a_unique)}
        b_index = {value: idx for idx, value in enumerate(b_unique)}

        h_grid = np.full((len(a_unique), len(b_unique)), np.nan, dtype=float)
        for a, b, h in zip(a_vals, b_vals, h_vals):
            ai = a_index[a]
            bi = b_index[b]
            if np.isnan(h_grid[ai, bi]) or h > h_grid[ai, bi]:
                h_grid[ai, bi] = h

        missing = int(np.isnan(h_grid).sum())
        score = (missing, -(len(a_unique) * len(b_unique)))
        candidate = (score, a_unique, b_unique, h_grid, tuple(axis_names[i] for i in plane_axes), axis_names[height_axis])
        if best is None or candidate[0] < best[0]:
            best = candidate

    assert best is not None
    _, x_values, y_values, z_grid, plane_axis_names, height_axis_name = best

    if np.isnan(z_grid).any():
        missing = int(np.isnan(z_grid).sum())
        raise ValueError(
            "Could not build a complete regular terrain grid from the STL. "
            f"Missing {missing} cells even after auto-detecting terrain axes."
        )

    return TerrainGrid(
        x_values=x_values,
        y_values=y_values,
        z_grid=z_grid,
        plane_axis_names=plane_axis_names,
        height_axis_name=height_axis_name,
    )


def create_solid_terrain_mesh(grid: TerrainGrid, base_thickness: float) -> trimesh.Trimesh:
    """
    Build a watertight terrain block from a height grid.

    Top surface = terrain heightfield
    Bottom surface = flat plane below the minimum terrain elevation
    Sides = vertical walls closing the block
    """
    xs = grid.x_values
    ys = grid.y_values
    z = grid.z_grid

    nx = len(xs)
    ny = len(ys)
    bottom_z = grid.z_min - float(base_thickness)

    top_vertices: List[List[float]] = []
    bottom_vertices: List[List[float]] = []
    for i, xv in enumerate(xs):
        for j, yv in enumerate(ys):
            top_vertices.append([float(xv), float(yv), float(z[i, j])])
            bottom_vertices.append([float(xv), float(yv), bottom_z])

    vertices = np.array(top_vertices + bottom_vertices, dtype=float)
    faces: List[List[int]] = []

    def top_idx(i: int, j: int) -> int:
        return i * ny + j

    def bottom_idx(i: int, j: int) -> int:
        return nx * ny + i * ny + j

    # Top faces
    for i in range(nx - 1):
        for j in range(ny - 1):
            a = top_idx(i, j)
            b = top_idx(i + 1, j)
            c = top_idx(i + 1, j + 1)
            d = top_idx(i, j + 1)
            faces.append([a, b, c])
            faces.append([a, c, d])

    # Bottom faces (reverse orientation)
    for i in range(nx - 1):
        for j in range(ny - 1):
            a = bottom_idx(i, j)
            b = bottom_idx(i + 1, j)
            c = bottom_idx(i + 1, j + 1)
            d = bottom_idx(i, j + 1)
            faces.append([a, c, b])
            faces.append([a, d, c])

    # Side walls: y = min edge
    j = 0
    for i in range(nx - 1):
        t1 = top_idx(i, j)
        t2 = top_idx(i + 1, j)
        b1 = bottom_idx(i, j)
        b2 = bottom_idx(i + 1, j)
        faces.append([t1, b2, b1])
        faces.append([t1, t2, b2])

    # Side walls: y = max edge
    j = ny - 1
    for i in range(nx - 1):
        t1 = top_idx(i, j)
        t2 = top_idx(i + 1, j)
        b1 = bottom_idx(i, j)
        b2 = bottom_idx(i + 1, j)
        faces.append([t1, b1, b2])
        faces.append([t1, b2, t2])

    # Side walls: x = min edge
    i = 0
    for j in range(ny - 1):
        t1 = top_idx(i, j)
        t2 = top_idx(i, j + 1)
        b1 = bottom_idx(i, j)
        b2 = bottom_idx(i, j + 1)
        faces.append([t1, b1, b2])
        faces.append([t1, b2, t2])

    # Side walls: x = max edge
    i = nx - 1
    for j in range(ny - 1):
        t1 = top_idx(i, j)
        t2 = top_idx(i, j + 1)
        b1 = bottom_idx(i, j)
        b2 = bottom_idx(i, j + 1)
        faces.append([t1, b2, b1])
        faces.append([t1, t2, b2])

    solid = trimesh.Trimesh(vertices=vertices, faces=np.array(faces, dtype=np.int64), process=False)
    return cleanup_mesh(solid)


def sample_polyline(
    points_xy: Sequence[Tuple[float, float]],
    step: float,
    smooth: bool = True,
    smoothing: float = 0.0,
) -> np.ndarray:
    if len(points_xy) < 2:
        raise ValueError("Need at least two clicked points to build a route")

    pts = np.asarray(points_xy, dtype=float)

    # If too few points, just do linear sampling
    if len(pts) < 3 or not smooth:
        samples: List[np.ndarray] = []
        for idx in range(len(pts) - 1):
            start = pts[idx]
            end = pts[idx + 1]
            segment = end - start
            length = float(np.linalg.norm(segment))
            if length <= 1e-9:
                continue
            count = max(2, int(math.ceil(length / step)) + 1)
            t = np.linspace(0.0, 1.0, count)
            seg_points = start[None, :] + t[:, None] * segment[None, :]
            if idx > 0:
                seg_points = seg_points[1:]
            samples.append(seg_points)

        if not samples:
            raise ValueError("Could not sample a route from the clicked points")
        return np.vstack(samples)

    # Arc-length parameterization
    diffs = np.diff(pts, axis=0)
    seg_lengths = np.linalg.norm(diffs, axis=1)
    total_length = float(np.sum(seg_lengths))
    if total_length <= 1e-9:
        raise ValueError("Clicked points are too close together")

    u = np.zeros(len(pts), dtype=float)
    u[1:] = np.cumsum(seg_lengths) / total_length

    # spline degree: up to cubic, but limited by number of points
    k = min(3, len(pts) - 1)

    # Build spline
    tck, _ = splprep(
        [pts[:, 0], pts[:, 1]],
        u=u,
        s=smoothing,
        k=k,
    )

    num_samples = max(2, int(math.ceil(total_length / step)) + 1)
    u_fine = np.linspace(0.0, 1.0, num_samples)
    x_smooth, y_smooth = splev(u_fine, tck)

    return np.column_stack([x_smooth, y_smooth])


def build_route_mesh(
    interpolator: HeightfieldInterpolator,
    sampled_xy: np.ndarray,
    route_width: float,
    route_height: float,
    terrain_overlap: float,
) -> trimesh.Trimesh:
    sampled_xy = np.asarray(sampled_xy, dtype=float)
    if len(sampled_xy) < 2:
        raise ValueError("Need at least two sampled points to build a route mesh")

    cap_segments = 12  # increase to 16 or 20 if you want even rounder ends

    center_z = interpolator.many(sampled_xy)

    # Compute tangent at each point
    tangents = np.zeros_like(sampled_xy)
    tangents[0] = sampled_xy[1] - sampled_xy[0]
    tangents[-1] = sampled_xy[-1] - sampled_xy[-2]
    if len(sampled_xy) > 2:
        tangents[1:-1] = sampled_xy[2:] - sampled_xy[:-2]

    tangent_norms = np.linalg.norm(tangents, axis=1, keepdims=True)
    tangent_norms[tangent_norms < 1e-12] = 1.0
    tangents = tangents / tangent_norms

    # 2D normals (left/right)
    normals = np.column_stack([-tangents[:, 1], tangents[:, 0]])
    normal_norms = np.linalg.norm(normals, axis=1, keepdims=True)
    normal_norms[normal_norms < 1e-12] = 1.0
    normals = normals / normal_norms

    half_width = route_width / 2.0
    left_xy = sampled_xy + half_width * normals
    right_xy = sampled_xy - half_width * normals

    def safe_sample_z(xy: np.ndarray, fallback: np.ndarray) -> np.ndarray:
        try:
            return interpolator.many(xy)
        except Exception:
            return fallback.copy()

    left_z = safe_sample_z(left_xy, center_z)
    right_z = safe_sample_z(right_xy, center_z)

    left_bottom_z = left_z - terrain_overlap
    right_bottom_z = right_z - terrain_overlap
    left_top_z = left_bottom_z + route_height
    right_top_z = right_bottom_z + route_height

    vertices: List[List[float]] = []
    faces: List[List[int]] = []

    # Per centerline point:
    # 0 = left_top, 1 = right_top, 2 = left_bottom, 3 = right_bottom
    for i in range(len(sampled_xy)):
        vertices.append([left_xy[i, 0], left_xy[i, 1], left_top_z[i]])
        vertices.append([right_xy[i, 0], right_xy[i, 1], right_top_z[i]])
        vertices.append([left_xy[i, 0], left_xy[i, 1], left_bottom_z[i]])
        vertices.append([right_xy[i, 0], right_xy[i, 1], right_bottom_z[i]])

    def idx(i: int, which: int) -> int:
        return 4 * i + which

    n = len(sampled_xy)

    # Main ribbon body
    for i in range(n - 1):
        lt0, rt0, lb0, rb0 = idx(i, 0), idx(i, 1), idx(i, 2), idx(i, 3)
        lt1, rt1, lb1, rb1 = idx(i + 1, 0), idx(i + 1, 1), idx(i + 1, 2), idx(i + 1, 3)

        # Top surface
        faces.append([lt0, rt0, rt1])
        faces.append([lt0, rt1, lt1])

        # Bottom surface
        faces.append([lb0, rb1, rb0])
        faces.append([lb0, lb1, rb1])

        # Left side
        faces.append([lt0, lt1, lb1])
        faces.append([lt0, lb1, lb0])

        # Right side
        faces.append([rt0, rb1, rt1])
        faces.append([rt0, rb0, rb1])

    def add_rounded_cap(
        center_xy: np.ndarray,
        tangent_xy: np.ndarray,
        normal_xy: np.ndarray,
        center_z_value: float,
        left_top_idx: int,
        right_top_idx: int,
        left_bottom_idx: int,
        right_bottom_idx: int,
        outward_sign: float,
    ) -> None:
        nonlocal vertices, faces

        # Arc from left edge to right edge, bulging outward
        angles = np.linspace(np.pi / 2.0, -np.pi / 2.0, cap_segments + 1)

        outward = outward_sign * tangent_xy
        arc_xy = []
        for theta in angles:
            direction = np.cos(theta) * outward + np.sin(theta) * normal_xy
            arc_xy.append(center_xy + half_width * direction)
        arc_xy = np.asarray(arc_xy, dtype=float)

        arc_center_fallback = np.full(len(arc_xy), center_z_value, dtype=float)
        arc_z = safe_sample_z(arc_xy, arc_center_fallback)

        arc_bottom_z = arc_z - terrain_overlap
        arc_top_z = arc_bottom_z + route_height

        start_top_ids = [left_top_idx]
        start_bottom_ids = [left_bottom_idx]

        # add only interior arc points; endpoints are existing ribbon vertices
        for k in range(1, len(arc_xy) - 1):
            top_id = len(vertices)
            vertices.append([arc_xy[k, 0], arc_xy[k, 1], arc_top_z[k]])
            bot_id = len(vertices)
            vertices.append([arc_xy[k, 0], arc_xy[k, 1], arc_bottom_z[k]])
            start_top_ids.append(top_id)
            start_bottom_ids.append(bot_id)

        start_top_ids.append(right_top_idx)
        start_bottom_ids.append(right_bottom_idx)

        center_top_id = len(vertices)
        vertices.append([center_xy[0], center_xy[1], center_z_value - terrain_overlap + route_height])
        center_bottom_id = len(vertices)
        vertices.append([center_xy[0], center_xy[1], center_z_value - terrain_overlap])

        # Top cap fan
        for a, b in zip(start_top_ids[:-1], start_top_ids[1:]):
            faces.append([center_top_id, a, b])

        # Bottom cap fan
        for a, b in zip(start_bottom_ids[:-1], start_bottom_ids[1:]):
            faces.append([center_bottom_id, b, a])

        # Curved outer wall
        for ta, tb, ba, bb in zip(
            start_top_ids[:-1],
            start_top_ids[1:],
            start_bottom_ids[:-1],
            start_bottom_ids[1:],
        ):
            faces.append([ta, tb, bb])
            faces.append([ta, bb, ba])

    # Rounded start cap
    add_rounded_cap(
        center_xy=sampled_xy[0],
        tangent_xy=tangents[0],
        normal_xy=normals[0],
        center_z_value=center_z[0],
        left_top_idx=idx(0, 0),
        right_top_idx=idx(0, 1),
        left_bottom_idx=idx(0, 2),
        right_bottom_idx=idx(0, 3),
        outward_sign=-1.0,  # start cap bulges backward
    )

    # Rounded end cap
    add_rounded_cap(
        center_xy=sampled_xy[-1],
        tangent_xy=tangents[-1],
        normal_xy=normals[-1],
        center_z_value=center_z[-1],
        left_top_idx=idx(n - 1, 0),
        right_top_idx=idx(n - 1, 1),
        left_bottom_idx=idx(n - 1, 2),
        right_bottom_idx=idx(n - 1, 3),
        outward_sign=1.0,  # end cap bulges forward
    )

    route_mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=float),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )

    return cleanup_mesh(route_mesh)

def export_route_only_glb(output_path: Path, route_mesh: trimesh.Trimesh) -> None:
    route_copy = route_mesh.copy()
    route_copy.visual.face_colors = np.tile(
        np.array([255, 140, 0, 255], dtype=np.uint8),
        (len(route_copy.faces), 1)
    )
    scene = trimesh.Scene()
    scene.add_geometry(route_copy, geom_name='route')
    glb_bytes = scene.export(file_type='glb')
    with open(output_path, 'wb') as f:
        f.write(glb_bytes)

def colorize_scene(
    terrain_mesh: trimesh.Trimesh,
    route_mesh: trimesh.Trimesh,
    terrain_rgba: Tuple[int, int, int, int] = (170, 170, 170, 255),
    route_rgba: Tuple[int, int, int, int] = (255, 140, 0, 255),
) -> trimesh.Scene:
    terrain_copy = terrain_mesh.copy()
    route_copy = route_mesh.copy()
    terrain_copy.visual.face_colors = np.tile(np.array(terrain_rgba, dtype=np.uint8), (len(terrain_copy.faces), 1))
    route_copy.visual.face_colors = np.tile(np.array(route_rgba, dtype=np.uint8), (len(route_copy.faces), 1))
    scene = trimesh.Scene()
    scene.add_geometry(terrain_copy, geom_name='terrain')
    scene.add_geometry(route_copy, geom_name='route')
    return scene


class RouteDrawer:
    def __init__(self, grid: TerrainGrid, flip_x: bool = False, flip_y: bool = False):
        self.grid = grid
        self.flip_x = flip_x
        self.flip_y = flip_y
        self.points: List[Tuple[float, float]] = []
        self.done = False
        self.cancelled = False

        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.line = Line2D([], [], color='orange', linewidth=2.0, marker='o', markersize=5)
        self.ax.add_line(self.line)

        self._draw_background()
        self._refresh_overlay()

        self.cid_click = self.fig.canvas.mpl_connect('button_press_event', self._on_click)
        self.cid_key = self.fig.canvas.mpl_connect('key_press_event', self._on_key)

    def _draw_background(self) -> None:
        z = self.grid.z_grid.T
        self.ax.imshow(
            z,
            extent=(self.grid.x_min, self.grid.x_max, self.grid.y_min, self.grid.y_max),
            origin='lower',
            cmap='gray',
            interpolation='nearest',
            aspect='equal',
        )
        contour_levels = np.linspace(self.grid.z_min, self.grid.z_max, 12)
        self.ax.contour(
            self.grid.x_values,
            self.grid.y_values,
            self.grid.z_grid.T,
            levels=contour_levels,
            linewidths=0.3,
            colors='black',
            alpha=0.35,
        )
        self.ax.set_title(
            'Click to draw the route on the terrain\n'
            'Left click = add point | U/Backspace = undo | C = clear | Enter = export | Esc = quit'
        )
        self.ax.set_xlabel(self.grid.plane_axis_names[0].upper())
        self.ax.set_ylabel(self.grid.plane_axis_names[1].upper())

        # NEW: flip display only
        if self.flip_x:
            self.ax.set_xlim(self.grid.x_max, self.grid.x_min)
        else:
            self.ax.set_xlim(self.grid.x_min, self.grid.x_max)

        if self.flip_y:
            self.ax.set_ylim(self.grid.y_max, self.grid.y_min)
        else:
            self.ax.set_ylim(self.grid.y_min, self.grid.y_max)

    def _refresh_overlay(self) -> None:
        if self.points:
            xs, ys = zip(*self.points)
            self.line.set_data(xs, ys)
        else:
            self.line.set_data([], [])
        self.fig.canvas.draw_idle()

    def _on_click(self, event) -> None:
        if event.inaxes != self.ax or event.button != 1:
            return
        if event.xdata is None or event.ydata is None:
            return
        self.points.append((float(event.xdata), float(event.ydata)))
        self._refresh_overlay()

    def _on_key(self, event) -> None:
        key = (event.key or '').lower()
        if key in {'u', 'backspace'}:
            if self.points:
                self.points.pop()
                self._refresh_overlay()
        elif key == 'c':
            self.points.clear()
            self._refresh_overlay()
        elif key == 'enter':
            self.done = True
            plt.close(self.fig)
        elif key == 'escape':
            self.cancelled = True
            plt.close(self.fig)

    def get_points(self) -> List[Tuple[float, float]]:
        plt.show()
        if self.cancelled:
            raise KeyboardInterrupt('User cancelled route drawing')
        if not self.done:
            raise RuntimeError('Drawing window closed before finishing. Press Enter to export.')
        if len(self.points) < 2:
            raise ValueError('Need at least two route points before exporting')
        return self.points


def save_preview_png(
    output_path: Path,
    grid: TerrainGrid,
    points_xy: Sequence[Tuple[float, float]],
    flip_x: bool = False,
    flip_y: bool = False,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.imshow(
        grid.z_grid.T,
        extent=(grid.x_min, grid.x_max, grid.y_min, grid.y_max),
        origin='lower',
        cmap='gray',
        interpolation='nearest',
        aspect='equal',
    )
    contour_levels = np.linspace(grid.z_min, grid.z_max, 12)
    ax.contour(
        grid.x_values,
        grid.y_values,
        grid.z_grid.T,
        levels=contour_levels,
        linewidths=0.3,
        colors='black',
        alpha=0.35,
    )
    xs, ys = zip(*points_xy)
    ax.plot(xs, ys, color='orange', linewidth=2.0, marker='o', markersize=4)
    ax.set_title('Route preview')
    ax.set_xlabel(grid.plane_axis_names[0].upper())
    ax.set_ylabel(grid.plane_axis_names[1].upper())

    # NEW: flip display only
    if flip_x:
        ax.set_xlim(grid.x_max, grid.x_min)
    else:
        ax.set_xlim(grid.x_min, grid.x_max)

    if flip_y:
        ax.set_ylim(grid.y_max, grid.y_min)
    else:
        ax.set_ylim(grid.y_min, grid.y_max)

    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)

def mirror_mesh_for_export(
    mesh: trimesh.Trimesh,
    grid: TerrainGrid,
    flip_x: bool = False,
    flip_y: bool = False,
) -> trimesh.Trimesh:
    if not (flip_x or flip_y):
        return mesh

    mirrored = mesh.copy()
    verts = mirrored.vertices.copy()

    x_mid = 0.5 * (grid.x_min + grid.x_max)
    y_mid = 0.5 * (grid.y_min + grid.y_max)

    if flip_x:
        verts[:, 0] = 2.0 * x_mid - verts[:, 0]

    if flip_y:
        verts[:, 1] = 2.0 * y_mid - verts[:, 1]

    mirrored.vertices = verts

    # Mirroring reverses face winding, so fix normals
    mirrored.faces = mirrored.faces[:, ::-1]

    return cleanup_mesh(mirrored)

def export_outputs(
    output_dir: Path,
    original_input: Path,
    clicked_points: Sequence[Tuple[float, float]],
    terrain_mesh: trimesh.Trimesh,
    route_mesh: trimesh.Trimesh,
    grid: TerrainGrid,
    flip_x: bool = False,
    flip_y: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / 'route_points.json', 'w', encoding='utf-8') as f:
        json.dump(
            {
                'input_file': str(original_input),
                'points_xy': [[float(x), float(y)] for x, y in clicked_points],
            },
            f,
            indent=2,
        )

    # Mirror exported geometry too, not just the preview
    terrain_export = mirror_mesh_for_export(
        terrain_mesh, grid, flip_x=flip_x, flip_y=flip_y
    )
    route_export = mirror_mesh_for_export(
        route_mesh, grid, flip_x=flip_x, flip_y=flip_y
    )

    save_preview_png(
        output_dir / 'route_preview.png',
        grid,
        clicked_points,
        flip_x=flip_x,
        flip_y=flip_y,
    )

    terrain_export.export(output_dir / 'terrain_solid.stl')
    route_export.export(output_dir / 'route_overlay_only.stl')

    combined_mesh = cleanup_mesh(
        trimesh.util.concatenate([terrain_export, route_export])
    )
    combined_mesh.export(output_dir / 'terrain_with_route_combined.stl')

    export_route_only_glb(
        output_dir / 'route_overlay_only_orange_preview.glb',
        route_export,
    )

    scene = colorize_scene(terrain_export, route_export)
    glb_bytes = scene.export(file_type='glb')
    with open(output_dir / 'terrain_with_orange_route_preview.glb', 'wb') as f:
        f.write(glb_bytes)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Draw a route on a terrain STL and export a printable souvenir model.')
    parser.add_argument('--input', required=True, help='Path to terrain STL file')
    parser.add_argument('--output-dir', default='terrain_route_output', help='Directory for exported files')
    parser.add_argument('--base-thickness', type=float, default=5.0, help='Flat base thickness added under the terrain')
    parser.add_argument('--route-width', type=float, default=1.4, help='Raised route width in model units (usually mm)')
    parser.add_argument('--route-height', type=float, default=0.8, help='Raised route height above the terrain surface')
    parser.add_argument('--terrain-overlap', type=float, default=0.2, help='How much the route slightly sinks into terrain for better printable overlap')
    parser.add_argument('--sample-step', type=float, default=0.8, help='Sampling step along the drawn polyline')
    parser.add_argument('--points-json', default=None, help='Optional JSON file with {"points_xy": [[x, y], ...]} to skip the interactive drawing window')

    # NEW
    parser.add_argument('--flip-x', action='store_true', help='Flip the displayed terrain left/right (display only)')
    parser.add_argument('--flip-y', action='store_true', help='Flip the displayed terrain up/down (display only)')
    parser.add_argument('--no-smooth', action='store_true', help='Disable spline smoothing and keep straight segments')
    parser.add_argument('--smoothing', type=float, default=0.0, help='Spline smoothing amount; 0 keeps the curve passing through points')



    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not input_path.exists():
        raise FileNotFoundError(f'Input STL not found: {input_path}')

    mesh = load_mesh(input_path)
    grid = build_height_grid(mesh)
    interpolator = HeightfieldInterpolator(grid)

    print('Loaded terrain STL')
    print(f'  {grid.plane_axis_names[0]} range: {grid.x_min:.3f} .. {grid.x_max:.3f}')
    print(f'  {grid.plane_axis_names[1]} range: {grid.y_min:.3f} .. {grid.y_max:.3f}')
    print(f'  {grid.height_axis_name} range: {grid.z_min:.3f} .. {grid.z_max:.3f}')
    if args.points_json:
        points_path = Path(args.points_json).expanduser().resolve()
        with open(points_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        clicked_points = [tuple(map(float, pair)) for pair in payload['points_xy']]
        print(f'Loaded {len(clicked_points)} route points from: {points_path}')
    else:
        print('A drawing window will open. Click the route, then press Enter to export.')
        drawer = RouteDrawer(grid, flip_x=args.flip_x, flip_y=args.flip_y)
        clicked_points = drawer.get_points()

    print('Sampling polyline...')
    sampled_xy = sample_polyline(
        clicked_points,
        step=float(args.sample_step),
        smooth=not args.no_smooth,
        smoothing=float(args.smoothing),
    )
    print(f'  sampled points: {len(sampled_xy)}')
    print('Building solid terrain mesh...')
    terrain_mesh = create_solid_terrain_mesh(grid, base_thickness=float(args.base_thickness))
    print('Building route mesh...')
    route_mesh = build_route_mesh(
        interpolator=interpolator,
        sampled_xy=sampled_xy,
        route_width=float(args.route_width),
        route_height=float(args.route_height),
        terrain_overlap=float(args.terrain_overlap),
    )

    print('Exporting files...')
    export_outputs(
        output_dir=output_dir,
        original_input=input_path,
        clicked_points=clicked_points,
        terrain_mesh=terrain_mesh,
        route_mesh=route_mesh,
        grid=grid,
        flip_x=args.flip_x,
        flip_y=args.flip_y,
        
    )

    print(f'Exported files to: {output_dir}')
    print('Files created:')
    print('  - terrain_solid.stl')
    print('  - route_overlay_only.stl')
    print('  - terrain_with_route_combined.stl')
    print('  - terrain_with_orange_route_preview.glb')
    print('  - route_preview.png')
    print('  - route_points.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
