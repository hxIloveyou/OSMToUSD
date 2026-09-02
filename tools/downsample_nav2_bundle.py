#!/usr/bin/env python3
"""Downsample a nav2/connected bundle to coarser resolution (default 3 m/px).

Connectivity rule (any-free):
  For each factor×factor block, if ANY source free pixel (254 or 255) is present,
  the output cell is FREE. Free is written as 255 (not ROS 254).

Writes a full nav2 sibling folder (does not overwrite --input):
  map.pgm, cost.pgm, map_local.yaml, map.yaml, valhalla_origin.yaml,
  map_meta.json, README.txt

Usage:
  python tools/downsample_nav2_bundle.py \\
    --input  output/ScenePackages/taibei_ue_20260902/nav2/connected \\
    --output output/ScenePackages/taibei_ue_20260902/nav2/variants/3m \\
    --factor 3
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# Source (CityUsd / Nav2 conventional) and destination free values.
SRC_FREE = 254
OUT_FREE = 255
OCCUPIED = 0
UNKNOWN = 205
COST_FREE = 0
COST_LETHAL = 254


def read_pgm(path: Path) -> np.ndarray:
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
    grid = np.frombuffer(raw[i:], dtype=np.uint8)
    if grid.size != w * h:
        raise ValueError(f"{path}: size mismatch {grid.size} != {w}*{h}")
    return grid.reshape(h, w).copy()


def write_pgm(path: Path, grid: np.ndarray) -> None:
    ny, nx = grid.shape
    header = f"P5\n{nx} {ny}\n255\n".encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + np.ascontiguousarray(grid, dtype=np.uint8).tobytes())


def _is_free(arr: np.ndarray) -> np.ndarray:
    """Treat both conventional 254 and already-converted 255 as free."""
    return (arr == SRC_FREE) | (arr == OUT_FREE)


def downsample_any_free(grid: np.ndarray, factor: int) -> np.ndarray:
    """Block OR of free → OUT_FREE(255); everything else → OCCUPIED(0)."""
    if factor < 2:
        raise ValueError("factor must be >= 2")
    h, w = grid.shape
    nh = int(math.ceil(h / factor))
    nw = int(math.ceil(w / factor))
    pad_h, pad_w = nh * factor, nw * factor
    padded = np.full((pad_h, pad_w), OCCUPIED, dtype=np.uint8)
    padded[:h, :w] = grid
    blocks = padded.reshape(nh, factor, nw, factor)
    free = _is_free(blocks).any(axis=(1, 3))
    return np.where(free, OUT_FREE, OCCUPIED).astype(np.uint8)


def _read_resolution(yaml_path: Path) -> float | None:
    if not yaml_path.is_file():
        return None
    for line in yaml_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("resolution:"):
            return float(line.split(":", 1)[1].strip())
    return None


def rewrite_yaml_resolution(src: Path, dst: Path, *, factor: int, image_name: str = "map.pgm") -> None:
    text = src.read_text(encoding="utf-8")
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("image:"):
            lines.append(f"image: {image_name}")
        elif line.startswith("resolution:"):
            old = float(line.split(":", 1)[1].strip())
            lines.append(f"resolution: {old * factor}")
        else:
            lines.append(line)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rewrite_meta(
    src: Path | None,
    dst: Path,
    grid: np.ndarray,
    resolution_m: float,
    *,
    factor: int,
) -> None:
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
    meta["occupancy_values"] = {"occupied": OCCUPIED, "free": OUT_FREE, "unknown": UNKNOWN}
    meta["pixel_0_0"] = meta.get("pixel_0_0", "northwest")
    meta["range_source"] = (
        str(meta.get("range_source") or "nav2")
        + f"_downsample_x{factor}_{resolution_m:g}m_free{OUT_FREE}"
    )
    meta["downsample"] = {
        "factor": int(factor),
        "rule": "any_source_free_254_or_255",
        "out_free": OUT_FREE,
        "src_free": SRC_FREE,
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def process(nav_dir: Path, out_dir: Path, *, factor: int) -> dict:
    src_map = nav_dir / "map.pgm"
    if not src_map.is_file():
        raise FileNotFoundError(f"missing {src_map}")

    grid = read_pgm(src_map)
    old_res = (
        _read_resolution(nav_dir / "map_local.yaml")
        or _read_resolution(nav_dir / "map.yaml")
        or 1.0
    )
    new_res = float(old_res) * factor
    out = downsample_any_free(grid, factor)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_pgm(out_dir / "map.pgm", out)
    # cost: free corridor = 0, lethal elsewhere (same geometry as map)
    cost = np.where(out == OUT_FREE, COST_FREE, COST_LETHAL).astype(np.uint8)
    write_pgm(out_dir / "cost.pgm", cost)

    for name in ("map_local.yaml", "map.yaml"):
        src = nav_dir / name
        if src.is_file():
            rewrite_yaml_resolution(src, out_dir / name, factor=factor)

    valhalla = nav_dir / "valhalla_origin.yaml"
    if valhalla.is_file():
        shutil.copy2(valhalla, out_dir / "valhalla_origin.yaml")

    rewrite_meta(nav_dir / "map_meta.json", out_dir / "map_meta.json", out, new_res, factor=factor)

    note = {
        "mode": "downsample_nav2_bundle",
        "factor": factor,
        "src_free": SRC_FREE,
        "out_free": OUT_FREE,
        "rule": "any free(254|255) in block → 255",
        "resolution_m": new_res,
        "source": str(nav_dir),
        "in_shape_hw": [int(grid.shape[0]), int(grid.shape[1])],
        "out_shape_hw": [int(out.shape[0]), int(out.shape[1])],
        "out_free_px": int((out == OUT_FREE).sum()),
        "out_occ_px": int((out == OCCUPIED).sum()),
    }
    (out_dir / "downsample_meta.json").write_text(
        json.dumps(note, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "README.txt").write_text(
        "Downsampled nav2 bundle (any-free keeps roads).\n"
        f"Source free {SRC_FREE} → output free {OUT_FREE}; occupied stays 0.\n"
        f"resolution_m: {old_res} → {new_res} (factor={factor}). Origin unchanged.\n"
        f"Source: {nav_dir}\n"
        "Tool: tools/downsample_nav2_bundle.py\n",
        encoding="utf-8",
    )
    return note


def write_align_overlay_for_bundle(
    package_dir: Path,
    nav_dir: Path,
    *,
    resolution_m: float,
    z_cm: float = 50.0,
) -> list[str]:
    """Write debug/nav_align_<res>m/ overlay USD for this nav2 folder."""
    from cityusd.nav_align_overlay import write_nav_align_overlay
    from cityusd.pipeline.terrain import load_extent_context

    _, _, extent = load_extent_context(package_dir)
    # Prefer coverage from map_meta if present (may pad slightly vs extent)
    tag = f"{resolution_m:g}m"
    rel = f"debug/nav_align_{tag}"
    return write_nav_align_overlay(
        package_dir,
        map_pgm=nav_dir / "map.pgm",
        map_meta_path=nav_dir / "map_meta.json",
        extent=extent,
        enabled=True,
        max_preview_side=4096,
        z_cm=z_cm,
        debug_rel_dir=rel,
        label=f"nav2 downsample {tag} (free=255)",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--package",
        type=Path,
        default=None,
        help="Scene package root (sets default --input/--output under nav2/)",
    )
    p.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Source nav2 dir with map.pgm (default: <package>/nav2/connected)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output nav2 dir (default: <package>/nav2/variants/<new_res>m)",
    )
    p.add_argument("--factor", type=int, default=3, help="Integer downsample factor (default 3 → 3 m/px from 1 m)")
    p.add_argument(
        "--write-align-overlay",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write debug/nav_align_<res>m/ USD plane (default: on)",
    )
    p.add_argument(
        "--overlay-only",
        action="store_true",
        help="Skip downsample; only write align overlay for an existing --output (or --input) nav2 dir",
    )
    p.add_argument("--z-cm", type=float, default=50.0, help="Overlay plane height in cm")
    args = p.parse_args(argv)

    if args.factor < 2 and not args.overlay_only:
        print("error: --factor must be >= 2", file=sys.stderr)
        return 2

    package = args.package.resolve() if args.package else None
    if args.input:
        nav_dir = args.input.resolve()
    elif package:
        nav_dir = package / "nav2" / "connected"
    else:
        print("error: need --input or --package", file=sys.stderr)
        return 2

    if not nav_dir.is_dir() and not args.overlay_only:
        print(f"error: input not found: {nav_dir}", file=sys.stderr)
        return 2

    old_res = (
        _read_resolution(nav_dir / "map_local.yaml")
        or _read_resolution(nav_dir / "map.yaml")
        or 1.0
    )
    new_res = float(old_res) * args.factor if not args.overlay_only else float(
        _read_resolution((args.output or nav_dir).resolve() / "map_local.yaml")
        or _read_resolution((args.output or nav_dir).resolve() / "map.yaml")
        or old_res
    )

    if args.output:
        out_dir = args.output.resolve()
    elif package and not args.overlay_only:
        out_dir = package / "nav2" / "variants" / f"{new_res:g}m"
    elif args.overlay_only:
        out_dir = nav_dir
    else:
        out_dir = nav_dir.parent / "variants" / f"{new_res:g}m"

    if not args.overlay_only:
        if out_dir == nav_dir:
            print("error: refuse overwrite of --input", file=sys.stderr)
            return 2
        if out_dir.name == "connected" and out_dir.parent.name == "nav2":
            print("error: refuse write into nav2/connected — pick variants/ or another path", file=sys.stderr)
            return 2
        note = process(nav_dir, out_dir, factor=int(args.factor))
        print("downsample_nav2_bundle OK")
        for k, v in note.items():
            print(f"  {k}: {v}")
        print(f"  output: {out_dir}")
        new_res = float(note["resolution_m"])
    else:
        if not (out_dir / "map.pgm").is_file():
            print(f"error: overlay-only needs map.pgm under {out_dir}", file=sys.stderr)
            return 2
        print(f"overlay-only for {out_dir}")

    # Resolve package root for debug/ overlay
    pkg_root = package
    if pkg_root is None:
        # .../nav2/variants/3m → package; .../nav2/connected → package
        cur = out_dir
        if cur.parent.name == "variants" and cur.parent.parent.name == "nav2":
            pkg_root = cur.parent.parent.parent
        elif cur.name == "connected" and cur.parent.name == "nav2":
            pkg_root = cur.parent.parent
        else:
            pkg_root = cur.parent

    if args.write_align_overlay:
        if not (pkg_root / "extent.json").is_file():
            print(f"warning: no extent.json under {pkg_root}; skip align overlay", file=sys.stderr)
        else:
            written = write_align_overlay_for_bundle(
                pkg_root,
                out_dir,
                resolution_m=new_res,
                z_cm=float(args.z_cm),
            )
            print("align overlay OK")
            for w in written:
                print(f"  {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
