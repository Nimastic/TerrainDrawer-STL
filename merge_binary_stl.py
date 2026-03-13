#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge multiple binary STL files into one binary STL."
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Merged STL output path",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Input binary STL files",
    )
    return parser.parse_args()


def read_binary_stl_payload(path: Path) -> tuple[int, bytes]:
    with path.open("rb") as f:
        header = f.read(80)
        if len(header) != 80:
            raise ValueError(f"Incomplete STL header: {path}")
        raw_count = f.read(4)
        if len(raw_count) != 4:
            raise ValueError(f"Incomplete STL triangle count: {path}")
        triangle_count = struct.unpack("<I", raw_count)[0]
        payload = f.read()
    expected_size = triangle_count * 50
    if len(payload) != expected_size:
        raise ValueError(
            f"Expected {expected_size} bytes of triangle data in {path}, got {len(payload)}"
        )
    return triangle_count, payload


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).expanduser().resolve()
    input_paths = [Path(item).expanduser().resolve() for item in args.inputs]

    total_triangles = 0
    payloads: list[bytes] = []
    for path in input_paths:
        if not path.exists():
            raise FileNotFoundError(f"Input STL not found: {path}")
        triangle_count, payload = read_binary_stl_payload(path)
        total_triangles += triangle_count
        payloads.append(payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        header = b"Merged binary STL"
        f.write(header + (b"\0" * (80 - len(header))))
        f.write(struct.pack("<I", total_triangles))
        for payload in payloads:
            f.write(payload)

    print(f"Output: {output_path}")
    print(f"Triangles written: {total_triangles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
