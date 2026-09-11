#!/usr/bin/env python3
"""Build a road costmap from an OSM-derived occupancy PGM and expand corridor width.

Does not modify the Scene Package pipeline or overwrite --input.

Typical flow (roads-only occupancy → width×scale → soft cost):
  python tools/build_road_cost_expand.py \\
    --input  <roads_only> --output <roads_x3> \\
    --width-scale 3 --inscribed-m 2.0

Width expansion (scale s):
  For each free pixel with EDT half-width h, dilate by (s-1)*h.
  A corridor of width W≈2h becomes ≈ s·W (e.g. s=3 → about triple width).
"""
# 中文说明：按倍率加宽道路走廊并生成软/硬代价图，不覆盖 --input。

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

try:
    from scipy.ndimage import distance_transform_edt, maximum_filter
except ImportError as exc:  # pragma: no cover
    raise ImportError("scipy required: pip install scipy") from exc

FREE = 254
OCCUPIED = 0
COST_FREE = 0
COST_LETHAL = 254
COST_MAX_INSCRIBED = 252


def read_pgm(path: Path) -> np.ndarray:
    """功能：读取 P5 PGM 栅格。"""
    raw = path.read_bytes()
    if not raw.startswith(b"P5"):
        raise ValueError(f"not P5: {path}")
    i = newlines = 0
    while i < len(raw) and newlines < 3:
        if raw[i] == 10:
            newlines += 1
        i += 1
    lines = [
        ln
        for ln in raw[:i].decode("ascii", errors="replace").splitlines()
        if ln and not ln.startswith("#")
    ]
    w, h = map(int, lines[1].split())
    data = np.frombuffer(raw[i:], dtype=np.uint8)
    if data.size != w * h:
        raise ValueError(f"{path}: size mismatch")
    return data.reshape(h, w).copy()


def write_pgm(path: Path, grid: np.ndarray) -> None:
    """功能：写出 P5 PGM。"""
    ny, nx = grid.shape
    header = f"P5\n{nx} {ny}\n255\n".encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + np.ascontiguousarray(grid, dtype=np.uint8).tobytes())


def read_resolution_m(nav_dir: Path) -> float:
    """功能：从 map.yaml 读取米/像素分辨率。"""
    yaml_path = nav_dir / "map.yaml"
    if not yaml_path.is_file():
        return 1.0
    for line in yaml_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("resolution:"):
            return float(line.split(":", 1)[1].strip())
    return 1.0


def expand_free_width_scale(free: np.ndarray, scale: float) -> np.ndarray:
    """功能：按局部半宽把自由走廊膨胀到约 scale 倍宽度。

    用 EDT 估计半宽 h，在脊线附近取 h，再把距原自由区 ≤ (scale-1)*h 的像素并入自由。
    """
    if scale <= 1.0 + 1e-9:
        return free.astype(bool, copy=True)
    free = free.astype(bool)
    if not np.any(free):
        return free

    hw = distance_transform_edt(free)  # 到障碍距离 ≈ 半宽
    # 半宽局部极大 ≈ 中轴脊
    ridge = free & (hw == maximum_filter(hw, size=5)) & (hw >= 1.0)
    if not np.any(ridge):
        ridge = free & (hw >= max(1.0, float(np.percentile(hw[free], 75))))

    _, (iy, ix) = distance_transform_edt(~ridge, return_indices=True)
    nearest_h = hw[iy, ix]
    # 限制超大开阔区（停车场等）的脊线半宽
    nearest_h = np.minimum(nearest_h, 64.0)

    dist_to_free = distance_transform_edt(~free)
    grow = (float(scale) - 1.0) * nearest_h
    return free | (dist_to_free <= grow)


def soft_cost_from_free_mask(
    free: np.ndarray,
    *,
    resolution_m: float,
    inscribed_m: float,
) -> np.ndarray:
    """功能：自由掩膜 → 软代价（同 MPPI 脚本逻辑）。"""
    obstacle = ~free
    dist_px = distance_transform_edt(~obstacle)
    dist_m = np.maximum(dist_px - 0.5, 0.0) * float(resolution_m)
    cost = np.full(free.shape, COST_LETHAL, dtype=np.uint8)
    inside = free
    if not np.any(inside):
        return cost
    insc = max(1e-6, float(inscribed_m))
    d = dist_m[inside]
    band = np.zeros(d.shape, dtype=np.uint8)
    deep = d >= insc
    band[deep] = COST_FREE
    edge = ~deep
    if np.any(edge):
        t = np.clip(d[edge] / insc, 0.0, 1.0)
        band[edge] = np.clip(
            np.round(COST_MAX_INSCRIBED * (1.0 - t)),
            1,
            COST_MAX_INSCRIBED,
        ).astype(np.uint8)
    cost[inside] = band
    return cost


def binary_cost(free: np.ndarray) -> np.ndarray:
    """功能：自由→0，否则致命 254。"""
    return np.where(free, COST_FREE, COST_LETHAL).astype(np.uint8)


def process(
    nav_dir: Path,
    out_dir: Path,
    *,
    width_scale: float,
    inscribed_m: float,
    soft_cost: bool,
) -> dict:
    """功能：加宽走廊并写出 map/cost 与元数据。"""
    src_map = nav_dir / "map.pgm"
    if not src_map.is_file():
        raise FileNotFoundError(f"missing {src_map}")

    grid = read_pgm(src_map)
    resolution_m = read_resolution_m(nav_dir)
    free0 = grid == FREE
    n_free_in = int(free0.sum())

    free = expand_free_width_scale(free0, width_scale)
    n_free_out = int(free.sum())

    occ_out = np.where(free, FREE, OCCUPIED).astype(np.uint8)
    if soft_cost:
        cost = soft_cost_from_free_mask(
            free, resolution_m=resolution_m, inscribed_m=inscribed_m
        )
    else:
        cost = binary_cost(free)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_pgm(out_dir / "map.pgm", occ_out)
    write_pgm(out_dir / "cost.pgm", cost)

    src_yaml = nav_dir / "map.yaml"
    if src_yaml.is_file():
        shutil.copy2(src_yaml, out_dir / "map.yaml")
    else:
        (out_dir / "map.yaml").write_text(
            f"image: map.pgm\nresolution: {resolution_m}\n"
            "origin: [0.0, 0.0, 0.0]\nnegate: 0\n"
            "occupied_thresh: 0.65\nfree_thresh: 0.196\n",
            encoding="utf-8",
        )

    meta = {
        "source_map": str(src_map),
        "resolution_m": resolution_m,
        "width_scale": width_scale,
        "inscribed_m": inscribed_m if soft_cost else None,
        "soft_cost": soft_cost,
        "size_px": [int(occ_out.shape[1]), int(occ_out.shape[0])],
        "free_in": n_free_in,
        "free_out": n_free_out,
        "free_ratio_out_over_in": (n_free_out / n_free_in) if n_free_in else None,
        "note": (
            "OSM-road occupancy expanded by local width×scale, then costmap. "
            "Sibling output; input unchanged."
        ),
    }
    (out_dir / "expand_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "README.txt").write_text(
        "Road costmap with corridor width expanded by --width-scale.\n"
        f"Source: {nav_dir.name}; scale={width_scale}; soft_cost={soft_cost}.\n"
        "Generated by tools/build_road_cost_expand.py — does not overwrite input.\n",
        encoding="utf-8",
    )
    return meta


def main(argv: list[str] | None = None) -> int:
    """功能：命令行入口。"""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, required=True, help="nav dir with OSM roads map.pgm (prefer roads_only)")
    p.add_argument("--output", type=Path, required=True, help="sibling output dir")
    p.add_argument("--width-scale", type=float, default=3.0, help="multiply local road width (default 3)")
    p.add_argument(
        "--inscribed-m",
        type=float,
        default=2.0,
        help="soft-cost free band depth in meters (default 2)",
    )
    p.add_argument(
        "--binary-cost",
        action="store_true",
        help="write hard 0/254 cost instead of soft EDT cost",
    )
    args = p.parse_args(argv)

    nav_dir = args.input.resolve()
    out_dir = args.output.resolve()
    if out_dir == nav_dir:
        print("error: --output must differ from --input", file=sys.stderr)
        return 2
    if args.width_scale <= 0:
        print("error: --width-scale must be positive", file=sys.stderr)
        return 2

    meta = process(
        nav_dir,
        out_dir,
        width_scale=float(args.width_scale),
        inscribed_m=float(args.inscribed_m),
        soft_cost=not bool(args.binary_cost),
    )
    print("build_road_cost_expand OK")
    for k, v in meta.items():
        if k == "note":
            continue
        print(f"  {k}: {v}")
    print(f"  output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
