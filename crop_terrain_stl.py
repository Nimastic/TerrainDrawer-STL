#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import struct
from bisect import bisect_right
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crop the right side of a terrain STL by rebuilding a watertight "
            "heightfield block without external dependencies."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input binary STL path",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output STL path",
    )
    parser.add_argument(
        "--crop-right-fraction",
        type=float,
        default=0.1,
        help="Fraction of the model width to remove from the positive X side",
    )
    return parser.parse_args()


def load_binary_stl_heightfield(path: Path) -> tuple[list[float], list[float], list[list[float]], float]:
    with path.open("rb") as f:
        header = f.read(80)
        if len(header) != 80:
            raise ValueError("STL header is incomplete")

        raw_count = f.read(4)
        if len(raw_count) != 4:
            raise ValueError("STL triangle count is incomplete")
        triangle_count = struct.unpack("<I", raw_count)[0]

        payload = f.read()
        expected_bytes = triangle_count * 50
        if len(payload) != expected_bytes:
            raise ValueError(
                f"Expected {expected_bytes} bytes of triangle data, got {len(payload)}"
            )

    x_values_set: set[float] = set()
    y_values_set: set[float] = set()
    max_z_by_xy: dict[tuple[float, float], float] = {}
    bottom_z = float("inf")

    for values in struct.iter_unpack("<12fH", payload):
        points = (
            (values[3], values[4], values[5]),
            (values[6], values[7], values[8]),
            (values[9], values[10], values[11]),
        )
        for x, y, z in points:
            x_values_set.add(x)
            y_values_set.add(y)
            if z < bottom_z:
                bottom_z = z

            key = (x, y)
            current = max_z_by_xy.get(key)
            if current is None or z > current:
                max_z_by_xy[key] = z

    x_values = sorted(x_values_set)
    y_values = sorted(y_values_set)

    if not x_values or not y_values:
        raise ValueError("No terrain coordinates were found in the STL")

    expected_points = len(x_values) * len(y_values)
    if len(max_z_by_xy) != expected_points:
        missing = expected_points - len(max_z_by_xy)
        raise ValueError(
            "The STL does not look like a regular terrain heightfield; "
            f"missing {missing} top-surface samples"
        )

    z_grid: list[list[float]] = []
    for x in x_values:
        column: list[float] = []
        for y in y_values:
            column.append(max_z_by_xy[(x, y)])
        z_grid.append(column)

    return x_values, y_values, z_grid, bottom_z


def crop_right_side(
    x_values: list[float],
    z_grid: list[list[float]],
    crop_fraction: float,
) -> tuple[list[float], list[list[float]], float]:
    if not 0.0 < crop_fraction < 1.0:
        raise ValueError("--crop-right-fraction must be between 0 and 1")

    x_min = x_values[0]
    x_max = x_values[-1]
    cut_x = x_min + (x_max - x_min) * (1.0 - crop_fraction)

    right_index = bisect_right(x_values, cut_x)
    if right_index <= 0 or right_index > len(x_values):
        raise ValueError("Crop position falls outside the terrain width")

    left_index = right_index - 1
    left_x = x_values[left_index]

    if math.isclose(left_x, cut_x, rel_tol=0.0, abs_tol=1e-7):
        return x_values[:right_index], [column[:] for column in z_grid[:right_index]], cut_x

    if right_index == len(x_values):
        raise ValueError("Crop position reaches the far right edge; nothing would be removed")

    right_x = x_values[right_index]
    blend = (cut_x - left_x) / (right_x - left_x)

    cropped_x = list(x_values[:right_index])
    cropped_z = [column[:] for column in z_grid[:right_index]]
    boundary_column = [
        z_grid[left_index][row] + blend * (z_grid[right_index][row] - z_grid[left_index][row])
        for row in range(len(z_grid[left_index]))
    ]
    cropped_x.append(cut_x)
    cropped_z.append(boundary_column)
    return cropped_x, cropped_z, cut_x


def triangle_count(nx: int, ny: int) -> int:
    return (4 * (nx - 1) * (ny - 1)) + (4 * (nx - 1)) + (4 * (ny - 1))


def normal_for_triangle(a: tuple[float, float, float], b: tuple[float, float, float], c: tuple[float, float, float]) -> tuple[float, float, float]:
    abx = b[0] - a[0]
    aby = b[1] - a[1]
    abz = b[2] - a[2]
    acx = c[0] - a[0]
    acy = c[1] - a[1]
    acz = c[2] - a[2]

    nx = (aby * acz) - (abz * acy)
    ny = (abz * acx) - (abx * acz)
    nz = (abx * acy) - (aby * acx)
    length = math.sqrt((nx * nx) + (ny * ny) + (nz * nz))
    if length == 0.0:
        return 0.0, 0.0, 0.0
    return nx / length, ny / length, nz / length


def write_binary_stl(
    path: Path,
    x_values: list[float],
    y_values: list[float],
    z_grid: list[list[float]],
    bottom_z: float,
) -> None:
    nx = len(x_values)
    ny = len(y_values)
    if nx < 2 or ny < 2:
        raise ValueError("Need at least a 2x2 grid to build a solid terrain mesh")

    vertices: list[tuple[float, float, float]] = []
    for i, x in enumerate(x_values):
        for j, y in enumerate(y_values):
            vertices.append((x, y, z_grid[i][j]))
    for x in x_values:
        for y in y_values:
            vertices.append((x, y, bottom_z))

    def top_idx(i: int, j: int) -> int:
        return (i * ny) + j

    def bottom_idx(i: int, j: int) -> int:
        return (nx * ny) + (i * ny) + j

    def emit_triangle(f, a_idx: int, b_idx: int, c_idx: int) -> None:
        a = vertices[a_idx]
        b = vertices[b_idx]
        c = vertices[c_idx]
        nx_val, ny_val, nz_val = normal_for_triangle(a, b, c)
        f.write(
            struct.pack(
                "<12fH",
                nx_val,
                ny_val,
                nz_val,
                a[0],
                a[1],
                a[2],
                b[0],
                b[1],
                b[2],
                c[0],
                c[1],
                c[2],
                0,
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        header = b"Cropped terrain STL"
        f.write(header + (b"\0" * (80 - len(header))))
        f.write(struct.pack("<I", triangle_count(nx, ny)))

        for i in range(nx - 1):
            for j in range(ny - 1):
                a = top_idx(i, j)
                b = top_idx(i + 1, j)
                c = top_idx(i + 1, j + 1)
                d = top_idx(i, j + 1)
                emit_triangle(f, a, b, c)
                emit_triangle(f, a, c, d)

        for i in range(nx - 1):
            for j in range(ny - 1):
                a = bottom_idx(i, j)
                b = bottom_idx(i + 1, j)
                c = bottom_idx(i + 1, j + 1)
                d = bottom_idx(i, j + 1)
                emit_triangle(f, a, c, b)
                emit_triangle(f, a, d, c)

        j = 0
        for i in range(nx - 1):
            t1 = top_idx(i, j)
            t2 = top_idx(i + 1, j)
            b1 = bottom_idx(i, j)
            b2 = bottom_idx(i + 1, j)
            emit_triangle(f, t1, b2, b1)
            emit_triangle(f, t1, t2, b2)

        j = ny - 1
        for i in range(nx - 1):
            t1 = top_idx(i, j)
            t2 = top_idx(i + 1, j)
            b1 = bottom_idx(i, j)
            b2 = bottom_idx(i + 1, j)
            emit_triangle(f, t1, b1, b2)
            emit_triangle(f, t1, b2, t2)

        i = 0
        for j in range(ny - 1):
            t1 = top_idx(i, j)
            t2 = top_idx(i, j + 1)
            b1 = bottom_idx(i, j)
            b2 = bottom_idx(i, j + 1)
            emit_triangle(f, t1, b1, b2)
            emit_triangle(f, t1, b2, t2)

        i = nx - 1
        for j in range(ny - 1):
            t1 = top_idx(i, j)
            t2 = top_idx(i, j + 1)
            b1 = bottom_idx(i, j)
            b2 = bottom_idx(i, j + 1)
            emit_triangle(f, t1, b2, b1)
            emit_triangle(f, t1, t2, b2)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"Input STL not found: {input_path}")

    x_values, y_values, z_grid, bottom_z = load_binary_stl_heightfield(input_path)
    cropped_x, cropped_z, cut_x = crop_right_side(
        x_values=x_values,
        z_grid=z_grid,
        crop_fraction=float(args.crop_right_fraction),
    )
    write_binary_stl(
        path=output_path,
        x_values=cropped_x,
        y_values=y_values,
        z_grid=cropped_z,
        bottom_z=bottom_z,
    )

    original_width = x_values[-1] - x_values[0]
    new_width = cropped_x[-1] - cropped_x[0]
    removed_width = x_values[-1] - cropped_x[-1]
    top_min = min(min(column) for column in z_grid)
    base_thickness = top_min - bottom_z

    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Grid size: {len(x_values)} x {len(y_values)}")
    print(f"Cropped grid size: {len(cropped_x)} x {len(y_values)}")
    print(f"Original width: {original_width:.6f}")
    print(f"New width: {new_width:.6f}")
    print(f"Removed width: {removed_width:.6f}")
    print(f"Cut plane X: {cut_x:.6f}")
    print(f"Base thickness preserved: {base_thickness:.6f}")
    print(f"Triangles written: {triangle_count(len(cropped_x), len(y_values))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
