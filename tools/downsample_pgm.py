#!/usr/bin/env python3
"""Downsample an occupancy PGM by integer factor without breaking road connectivity.

For each factor×factor block:
  - if any pixel is FREE(254) → FREE
  - else if any is OCCUPIED(0) → OCCUPIED
  - else → UNKNOWN(205)  (or OCCUPIED when --binary-roads-only)

Also rewrites cost.pgm and map.yaml (resolution *= factor; same origin).

This avoids thin-road gaps that appear when re-rasterizing OSM polygons at
coarse resolution with all_touched=False.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

FREE = 254
OCCUPIED = 0
UNKNOWN = 205
COST_FREE = 0
COST_LETHAL = 254


def read_pgm(path: Path) -> tuple[bytes, np.ndarray]:
    raw = path.read_bytes()
    if not raw.startswith(b"P5"):
        raise ValueError(f"not P5: {path}")
    i = newlines = 0
    while i < len(raw) and newlines < 3:
        if raw[i] == 10:
            newlines += 1
        i += 1
    header = raw[:i]
    lines = [ln for ln in header.decode("ascii", errors="replace").splitlines() if ln and not ln.startswith("#")]
    w, h = map(int, lines[1].split())
    grid = np.frombuffer(raw[i:], dtype=np.uint8)
    if grid.size != w * h:
        raise ValueError(f"{path}: size mismatch")
    return header, grid.reshape(h, w).copy()


def write_pgm(path: Path, grid: np.ndarray) -> None:
    ny, nx = grid.shape
    header = f"P5\n{nx} {ny}\n255\n".encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + np.ascontiguousarray(grid, dtype=np.uint8).tobytes())


def downsample_occupancy(grid: np.ndarray, factor: int, *, binary: bool) -> np.ndarray:
    if factor < 2:
        raise ValueError("factor must be >= 2")
    h, w = grid.shape
    nh = int(math.ceil(h / factor))
    nw = int(math.ceil(w / factor))
    pad_h = nh * factor
    pad_w = nw * factor
    fill = OCCUPIED if binary else UNKNOWN
    padded = np.full((pad_h, pad_w), fill, dtype=np.uint8)
    padded[:h, :w] = grid
    blocks = padded.reshape(nh, factor, nw, factor)
    free = (blocks == FREE).any(axis=(1, 3))
    if binary:
        out = np.where(free, FREE, OCCUPIED).astype(np.uint8)
    else:
        occ = (blocks == OCCUPIED).any(axis=(1, 3))
        out = np.full((nh, nw), UNKNOWN, dtype=np.uint8)
        out[occ] = OCCUPIED
        out[free] = FREE
    return out


def rewrite_yaml(src: Path, dst: Path, *, factor: int, image_name: str = "map.pgm") -> None:
    text = src.read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith("image:"):
            lines.append(f"image: {image_name}")
        elif line.startswith("resolution:"):
            old = float(line.split(":", 1)[1].strip())
            lines.append(f"resolution: {old * factor}")
        else:
            lines.append(line)
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rewrite_meta(src: Path | None, dst: Path, grid: np.ndarray, resolution_m: float) -> None:
    if src is None or not src.is_file():
        return
    meta = json.loads(src.read_text(encoding="utf-8"))
    ny, nx = grid.shape
    meta["size_px"] = [int(nx), int(ny)]
    meta["meters_per_pixel"] = [float(resolution_m), float(resolution_m)]
    meta["resolution_m"] = float(resolution_m)
    if "coverage_m" in meta and "extent_m" in meta:
        west = float(meta["extent_m"]["west"])
        south = float(meta["extent_m"]["south"])
        meta["coverage_m"] = {
            "west": west,
            "south": south,
            "east": west + nx * resolution_m,
            "north": south + ny * resolution_m,
            "width": nx * resolution_m,
            "height": ny * resolution_m,
        }
    meta["occupancy_file"] = "map.pgm"
    meta["cost_file"] = "cost.pgm"
    meta["range_source"] = meta.get("range_source", "") + f"_downsample_{resolution_m:g}m"
    dst.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def process(
    nav_dir: Path,
    out_dir: Path,
    *,
    factor: int,
    binary: bool,
) -> dict:
    src_map = nav_dir / "map.pgm"
    header_ignored, grid = read_pgm(src_map)
    src_yaml = nav_dir / "map.yaml"
    # read old resolution
    old_res = 1.0
    if src_yaml.is_file():
        for line in src_yaml.read_text(encoding="utf-8").splitlines():
            if line.startswith("resolution:"):
                old_res = float(line.split(":", 1)[1].strip())
                break
    new_res = old_res * factor
    out = downsample_occupancy(grid, factor, binary=binary)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_pgm(out_dir / "map.pgm", out)
    cost = np.where(out == FREE, COST_FREE, COST_LETHAL).astype(np.uint8)
    write_pgm(out_dir / "cost.pgm", cost)
    if src_yaml.is_file():
        rewrite_yaml(src_yaml, out_dir / "map.yaml", factor=factor)
    rewrite_meta(nav_dir / "map_meta.json", out_dir / "map_meta.json", out, new_res)
    (out_dir / "README.txt").write_text(
        f"Downsampled ×{factor} from {nav_dir} (any-FREE-in-block keeps road).\n"
        f"resolution_m: {old_res} → {new_res}. Geographic origin unchanged.\n"
        f"binary_roads_only={binary}. Tool: tools/downsample_pgm.py\n",
        encoding="utf-8",
    )
    return {
        "in_shape": list(grid.shape),
        "out_shape": list(out.shape),
        "resolution_m": new_res,
        "out_free": int((out == FREE).sum()),
        "out_dir": str(out_dir),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--factor", type=int, default=3)
    p.add_argument(
        "--binary-roads-only",
        action="store_true",
        help="Non-free → occupied (no gray unknown)",
    )
    args = p.parse_args(argv)
    if args.output.resolve() == args.input.resolve():
        print("error: refuse overwrite of --input", file=sys.stderr)
        return 2
    stats = process(args.input.resolve(), args.output.resolve(), factor=args.factor, binary=args.binary_roads_only)
    print("downsample_pgm OK")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
