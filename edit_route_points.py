#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import trimesh
from matplotlib.lines import Line2D


@dataclass
class TerrainGrid:
    x_values: np.ndarray
    y_values: np.ndarray
    z_grid: np.ndarray
    plane_axis_names: Tuple[str, str] = ("x", "y")
    height_axis_name: str = "z"

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
    def z_min(self) -> float:
        return float(np.min(self.z_grid))

    @property
    def z_max(self) -> float:
        return float(np.max(self.z_grid))


def load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load_mesh(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Expected Trimesh, got {type(mesh)}")
    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ValueError("Empty STL")
    return mesh


def build_height_grid(mesh: trimesh.Trimesh, rounding_decimals: int = 6) -> TerrainGrid:
    vertices = np.asarray(mesh.vertices, dtype=float)
    axis_names = ["x", "y", "z"]

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
        candidate = (
            score,
            a_unique,
            b_unique,
            h_grid,
            tuple(axis_names[i] for i in plane_axes),
            axis_names[height_axis],
        )
        if best is None or candidate[0] < best[0]:
            best = candidate

    assert best is not None
    _, x_values, y_values, z_grid, plane_axis_names, height_axis_name = best

    if np.isnan(z_grid).any():
        missing = int(np.isnan(z_grid).sum())
        raise ValueError(
            f"Could not build complete terrain grid; missing {missing} cells."
        )

    return TerrainGrid(
        x_values=x_values,
        y_values=y_values,
        z_grid=z_grid,
        plane_axis_names=plane_axis_names,
        height_axis_name=height_axis_name,
    )


class RouteEditor:
    def __init__(
        self,
        grid: TerrainGrid,
        points: Sequence[Tuple[float, float]] | None = None,
        flip_x: bool = False,
        flip_y: bool = False,
    ):
        self.grid = grid
        self.points: List[Tuple[float, float]] = list(points or [])
        self.flip_x = flip_x
        self.flip_y = flip_y
        self.done = False
        self.cancelled = False

        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.line = Line2D([], [], color="orange", linewidth=2.0, marker="o", markersize=5)
        self.ax.add_line(self.line)

        self._draw_background()
        self._refresh_overlay()

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

    def _draw_background(self) -> None:
        self.ax.imshow(
            self.grid.z_grid.T,
            extent=(self.grid.x_min, self.grid.x_max, self.grid.y_min, self.grid.y_max),
            origin="lower",
            cmap="gray",
            interpolation="nearest",
            aspect="equal",
        )
        contour_levels = np.linspace(self.grid.z_min, self.grid.z_max, 12)
        self.ax.contour(
            self.grid.x_values,
            self.grid.y_values,
            self.grid.z_grid.T,
            levels=contour_levels,
            linewidths=0.3,
            colors="black",
            alpha=0.35,
        )

        self.ax.set_title(
            "Edit route points\n"
            "Left click = add | Right click = remove last | U/Backspace = undo | "
            "C = clear | S = save | Enter = save+quit | Esc = quit"
        )
        self.ax.set_xlabel(self.grid.plane_axis_names[0].upper())
        self.ax.set_ylabel(self.grid.plane_axis_names[1].upper())

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

    def _save_snapshot(self) -> None:
        pass

    def _on_click(self, event) -> None:
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return

        if event.button == 1:  # left click = add
            self.points.append((float(event.xdata), float(event.ydata)))
            self._refresh_overlay()
        elif event.button == 3:  # right click = remove last
            if self.points:
                self.points.pop()
                self._refresh_overlay()

    def _on_key(self, event) -> None:
        key = (event.key or "").lower()

        if key in {"u", "backspace"}:
            if self.points:
                self.points.pop()
                self._refresh_overlay()
        elif key == "c":
            self.points.clear()
            self._refresh_overlay()
        elif key == "s":
            print("Saved in memory; press Enter to finish writing file.")
        elif key == "enter":
            self.done = True
            plt.close(self.fig)
        elif key in {"escape", "q"}:
            self.cancelled = True
            plt.close(self.fig)

    def get_points(self) -> List[Tuple[float, float]]:
        plt.show()
        if self.cancelled:
            raise KeyboardInterrupt("User cancelled editing")
        if not self.done:
            raise RuntimeError("Window closed before finishing. Press Enter to save+quit.")
        if len(self.points) < 2:
            raise ValueError("Need at least two points")
        return self.points


def load_points_json(path: Path) -> tuple[str | None, List[Tuple[float, float]]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    input_file = payload.get("input_file")
    points = [tuple(map(float, pair)) for pair in payload["points_xy"]]
    return input_file, points


def save_points_json(path: Path, input_file: str | None, points: Sequence[Tuple[float, float]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "input_file": input_file,
                "points_xy": [[float(x), float(y)] for x, y in points],
            },
            f,
            indent=2,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Edit route_points.json on top of an STL terrain view")
    parser.add_argument("--input-stl", required=True, help="Terrain STL")
    parser.add_argument("--input-json", required=True, help="Existing route_points.json")
    parser.add_argument("--output-json", default=None, help="Output JSON path; default overwrites input-json")
    parser.add_argument("--flip-x", action="store_true", help="Flip display left/right")
    parser.add_argument("--flip-y", action="store_true", help="Flip display up/down")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    stl_path = Path(args.input_stl).expanduser().resolve()
    input_json_path = Path(args.input_json).expanduser().resolve()
    output_json_path = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json
        else input_json_path
    )

    if not stl_path.exists():
        raise FileNotFoundError(f"STL not found: {stl_path}")
    if not input_json_path.exists():
        raise FileNotFoundError(f"JSON not found: {input_json_path}")

    mesh = load_mesh(stl_path)
    grid = build_height_grid(mesh)
    original_input_file, points = load_points_json(input_json_path)

    print(f"Loaded STL: {stl_path}")
    print(f"Loaded {len(points)} existing points from: {input_json_path}")
    print("Editor controls:")
    print("  Left click  = add point")
    print("  Right click = remove last point")
    print("  U/Backspace = undo")
    print("  C           = clear all")
    print("  Enter       = save and quit")
    print("  Esc/Q       = quit without saving")

    editor = RouteEditor(
        grid=grid,
        points=points,
        flip_x=args.flip_x,
        flip_y=args.flip_y,
    )
    edited_points = editor.get_points()

    save_points_json(output_json_path, original_input_file, edited_points)
    print(f"Saved {len(edited_points)} points to: {output_json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())