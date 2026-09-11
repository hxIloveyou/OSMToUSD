#!/usr/bin/env python3
"""Build an MPPI-friendly soft costmap from a roads-only occupancy PGM.

Does not modify the Scene Package pipeline or overwrite the input directory.
Writes a sibling folder (e.g. nav_mppi/) with:

  map.pgm   — occupancy after closing (+ optional free inflate); FREE=254, else 0
  cost.pgm  — soft Nav2-style costs for MPPI / local planners:
                0     free corridor (distance to obstacle >= inscribed_m)
                1-252 rising cost toward road edge (distance transform)
                254   lethal (off-road / outside free mask)
  map.yaml  — same origin/resolution as input (image: map.pgm)

Pipeline:
  1. Treat FREE(254) as road; everything else as obstacle.
  2. Morphological closing on free mask (fill stair-step notches).
  3. Optional free dilation (navigation margin without changing USD widths).
  4. EDT from obstacles → soft cost inside free; lethal outside.

Usage:
  python tools/build_mppi_cost_pgm.py \\
    --input  <…/roads_only> --output <…/mppi> \\
    --close-m 1.5 --inflate-free-m 0.8 --inscribed-m 2.0
"""
# 中文说明：从 roads-only 生成 MPPI 软代价旁路包，不覆盖输入。

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

try:
    from scipy.ndimage import binary_closing, binary_dilation, distance_transform_edt
except ImportError as exc:  # pragma: no cover
    raise ImportError("scipy required: pip install scipy") from exc

FREE = 254
OCCUPIED = 0
COST_FREE = 0
COST_LETHAL = 254
COST_MAX_INSCRIBED = 252  # Nav2 inscribed-space band before lethal


def read_pgm(path: Path) -> tuple[np.ndarray, float | None]:
    """功能：读取 P5 PGM，返回栅格（第二项预留分辨率，当前为 None）。"""
    raw = path.read_bytes()
    if not raw.startswith(b"P5"):
        raise ValueError(f"not a binary PGM P5: {path}")
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
    if len(lines) < 3 or lines[0] != "P5":
        raise ValueError(f"unrecognized PGM header in {path}: {lines[:4]!r}")
    w, h = map(int, lines[1].split())
    maxval = int(lines[2])
    if maxval != 255:
        raise ValueError(f"expected maxval 255, got {maxval} in {path}")
    data = np.frombuffer(raw[i:], dtype=np.uint8)
    if data.size != w * h:
        raise ValueError(f"{path}: pixel count {data.size} != {w}*{h}")
    return data.reshape(h, w).copy(), None


def write_pgm(path: Path, grid: np.ndarray) -> None:
    """功能：写出 P5 PGM。"""
    ny, nx = grid.shape
    header = f"P5\n{nx} {ny}\n255\n".encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + np.ascontiguousarray(grid, dtype=np.uint8).tobytes())


def read_resolution_m(nav_dir: Path) -> float:
    """功能：从 map.yaml 读取 resolution（米/像素），缺省 1.0。"""
    yaml_path = nav_dir / "map.yaml"
    if not yaml_path.is_file():
        return 1.0
    for line in yaml_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("resolution:"):
            return float(line.split(":", 1)[1].strip())
    return 1.0


def disk_structure(radius_px: int) -> np.ndarray:
    """功能：生成半径为 radius_px 的圆形结构元素（形态学用）。"""
    r = max(1, int(radius_px))
    yy, xx = np.ogrid[-r : r + 1, -r : r + 1]
    return (xx * xx + yy * yy) <= (r * r)


def meters_to_radius_px(meters: float, resolution_m: float) -> int:
    """功能：把米制半径换算为像素半径（向上取整，至少 1）。"""
    if meters <= 0:
        return 0
    return max(1, int(math.ceil(float(meters) / float(resolution_m))))


def soft_cost_from_free_mask(
    free: np.ndarray,
    *,
    resolution_m: float,
    inscribed_m: float,
) -> np.ndarray:
    """功能：由自由掩膜生成 Nav2 风格软代价。

    走廊深处（距障 ≥ inscribed_m）为 0；靠近路缘升至 252；路外 254。
    距离由障碍 EDT 换算为米；半像素偏移近似到自由/障碍交界面。
    """
    obstacle = ~free
    # 自由像素到最近障碍的距离（像素）；减 0.5 使边缘单元进入软代价带
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
        # t→0 靠近障碍 → 高代价；t→1 靠近 inscribed → 低代价
        t = np.clip(d[edge] / insc, 0.0, 1.0)
        band[edge] = np.clip(
            np.round(COST_MAX_INSCRIBED * (1.0 - t)),
            1,
            COST_MAX_INSCRIBED,
        ).astype(np.uint8)
    cost[inside] = band
    return cost


def process(
    nav_dir: Path,
    out_dir: Path,
    *,
    close_m: float,
    inflate_free_m: float,
    inscribed_m: float,
) -> dict:
    """功能：闭运算/膨胀自由区并写出 map.pgm、cost.pgm 与附属文件。"""
    src_map = nav_dir / "map.pgm"
    if not src_map.is_file():
        raise FileNotFoundError(f"missing {src_map}")

    grid, _ = read_pgm(src_map)
    resolution_m = read_resolution_m(nav_dir)
    free0 = grid == FREE
    n_free_in = int(free0.sum())

    close_r = meters_to_radius_px(close_m, resolution_m) if close_m > 0 else 0
    inflate_r = meters_to_radius_px(inflate_free_m, resolution_m) if inflate_free_m > 0 else 0

    free = free0
    if close_r > 0:
        free = binary_closing(free, structure=disk_structure(close_r))
    if inflate_r > 0:
        free = binary_dilation(free, structure=disk_structure(inflate_r))

    occ_out = np.where(free, FREE, OCCUPIED).astype(np.uint8)
    cost = soft_cost_from_free_mask(
        free,
        resolution_m=resolution_m,
        inscribed_m=inscribed_m,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    write_pgm(out_dir / "map.pgm", occ_out)
    write_pgm(out_dir / "cost.pgm", cost)

    src_yaml = nav_dir / "map.yaml"
    if src_yaml.is_file():
        shutil.copy2(src_yaml, out_dir / "map.yaml")
    else:
        (out_dir / "map.yaml").write_text(
            "image: map.pgm\n"
            f"resolution: {resolution_m}\n"
            "origin: [0.0, 0.0, 0.0]\n"
            "negate: 0\n"
            "occupied_thresh: 0.65\n"
            "free_thresh: 0.196\n",
            encoding="utf-8",
        )

    meta = {
        "source_map": str(src_map),
        "resolution_m": resolution_m,
        "close_m": close_m,
        "close_radius_px": close_r,
        "inflate_free_m": inflate_free_m,
        "inflate_radius_px": inflate_r,
        "inscribed_m": inscribed_m,
        "size_px": [int(occ_out.shape[1]), int(occ_out.shape[0])],
        "free_in": n_free_in,
        "free_out": int(free.sum()),
        "cost_values": {
            "free": COST_FREE,
            "inscribed_max": COST_MAX_INSCRIBED,
            "lethal": COST_LETHAL,
        },
        "note": (
            "MPPI soft costmap: morphological closing + optional free inflate + "
            "EDT soft band. Sibling output; input nav not modified."
        ),
    }
    (out_dir / "mppi_cost_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "README.txt").write_text(
        "MPPI / local-planner soft costmap (sibling of roads-only nav).\n"
        f"Generated by tools/build_mppi_cost_pgm.py from {nav_dir.name}.\n"
        f"close_m={close_m}, inflate_free_m={inflate_free_m}, inscribed_m={inscribed_m}.\n"
        "Use cost.pgm + map.yaml for MPPI costmap; original nav/ cost.pgm unchanged.\n"
        "If cost already soft, reduce or disable Nav2 inflation_layer to avoid double-padding.\n",
        encoding="utf-8",
    )
    return meta


def main(argv: list[str] | None = None) -> int:
    """功能：命令行入口。返回 0 成功，2 拒绝覆盖输入。"""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, required=True, help="nav dir with map.pgm (prefer roads_only)")
    p.add_argument("--output", type=Path, required=True, help="sibling output dir (must differ from --input)")
    p.add_argument("--close-m", type=float, default=1.5, help="binary closing radius in meters (default 1.5)")
    p.add_argument(
        "--inflate-free-m",
        type=float,
        default=0.8,
        help="extra free dilation after closing, meters (default 0.8)",
    )
    p.add_argument(
        "--inscribed-m",
        type=float,
        default=2.0,
        help="soft-band width: cost=0 when dist-to-edge >= this (default 2.0 m)",
    )
    args = p.parse_args(argv)

    nav_dir = args.input.resolve()
    out_dir = args.output.resolve()
    if out_dir == nav_dir:
        print("error: --output must differ from --input (refusing overwrite)", file=sys.stderr)
        return 2
    if not nav_dir.is_dir():
        print(f"error: input not found: {nav_dir}", file=sys.stderr)
        return 1

    meta = process(
        nav_dir,
        out_dir,
        close_m=float(args.close_m),
        inflate_free_m=float(args.inflate_free_m),
        inscribed_m=float(args.inscribed_m),
    )
    print("build_mppi_cost_pgm OK")
    for k in (
        "source_map",
        "resolution_m",
        "close_m",
        "close_radius_px",
        "inflate_free_m",
        "inflate_radius_px",
        "inscribed_m",
        "size_px",
        "free_in",
        "free_out",
    ):
        print(f"  {k}: {meta[k]}")
    print(f"  output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
