#!/usr/bin/env python3
"""Build a sibling Scene Package: roads ×N wide, drop buildings on carriageways.

Copies terrain / water / veg / lamps / signs from an existing package, then
rebuilds only city_roads + city_buildings with --road-width-scale (buildings
that intersect the widened carriageway are dropped — existing footprint_after_roads).

Usage:
  python tools/build_roads_scaled_usd_package.py \\
    --source <existing USD package> \\
    --output <sibling package> \\
    --road-width-scale 2
"""
# 中文说明：旁路包——道路加宽并压掉车行道上建筑，不替代主包。

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
_ROOT = _TOOLS.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from cityusd.package import write_world  # noqa: E402
import build_city_usd  # noqa: E402

_COPY_LAYER_GLOBS = (
    "environment.usda",
    "terrain.usda",
    "nav.usda",
    "city_water.usdc",
    "city_water.usda",
    "city_vegetation.usdc",
    "city_vegetation.usda",
    "city_lamps.usdc",
    "city_lamps.usda",
    "city_signs.usdc",
    "city_signs.usda",
)

_COPY_TREE_NAMES = (
    "terrain",
    "textures",
    "models",
    "overlay",
    "inputs",
    "catalog",
    "configs",
)


def _copy_file(src: Path, dst: Path) -> None:
    """功能：确保父目录存在后复制单文件。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    """功能：整树复制（目标已存在则先删除）。"""
    if not src.is_dir():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def seed_package(source: Path, dest: Path) -> None:
    """功能：从源包拷贝可复用资源；不拷贝道路/建筑层（稍后重建）。"""
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("extent.json", "meta.json", "sources_manifest.json", "assets_used.json"):
        src = source / name
        if src.is_file():
            _copy_file(src, dest / name)
    for name in _COPY_TREE_NAMES:
        _copy_tree(source / name, dest / name)
    layers_src = source / "layers"
    layers_dst = dest / "layers"
    layers_dst.mkdir(parents=True, exist_ok=True)
    for name in _COPY_LAYER_GLOBS:
        src = layers_src / name
        if src.is_file():
            _copy_file(src, layers_dst / name)
    # 道路/建筑不复制，下面由 build_city_usd 重建


def assemble_world(dest: Path, scene_id: str) -> Path:
    """功能：按存在的图层组装 World_{scene_id}.usda。"""
    sublayers: list[str] = []
    for rel in (
        "./layers/environment.usda",
        "./layers/terrain.usda",
        "./layers/nav.usda",
        "./layers/city_water.usdc",
        "./layers/city_vegetation.usdc",
        "./layers/city_roads.usdc",
        "./layers/city_buildings.usdc",
        "./layers/city_lamps.usdc",
        "./layers/city_signs.usdc",
    ):
        path = dest / rel.removeprefix("./")
        alt = path.with_suffix(".usda") if path.suffix == ".usdc" else path.with_suffix(".usdc")
        if path.is_file():
            sublayers.append(rel)
        elif alt.is_file():
            sublayers.append("./" + alt.relative_to(dest).as_posix())
    for overlay in sorted((dest / "overlay").glob("*.usda")) if (dest / "overlay").is_dir() else []:
        sublayers.append("./" + overlay.relative_to(dest).as_posix())
    world_path = dest / f"World_{scene_id}.usda"
    write_world(world_path, scene_id, sublayers)
    return world_path


def main(argv: list[str] | None = None) -> int:
    """功能：播种旁路包 → 重建加宽道路/建筑 → 组装 World。"""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", type=Path, required=True, help="Existing Scene Package")
    p.add_argument("--output", type=Path, required=True, help="New sibling package dir")
    p.add_argument("--road-width-scale", type=float, default=2.0)
    p.add_argument("--scene-id", type=str, default=None)
    args = p.parse_args(argv)

    source = args.source.resolve()
    dest = args.output.resolve()
    if not source.is_dir():
        print(f"error: source not found: {source}", file=sys.stderr)
        return 1
    if dest == source:
        print("error: --output must differ from --source", file=sys.stderr)
        return 2
    if not (source / "extent.json").is_file():
        print("error: source missing extent.json", file=sys.stderr)
        return 1

    scene_id = args.scene_id or dest.name
    print(f"seed package {source.name} → {dest.name}", flush=True)
    seed_package(source, dest)

    staging = dest / "inputs" / "build_data"
    if not staging.is_dir():
        print(f"error: missing staged build_data under {staging}", file=sys.stderr)
        return 1

    print(
        f"rebuild roads+buildings road_width_scale={args.road_width_scale} ...",
        flush=True,
    )
    rc = build_city_usd.main(
        [
            "--data",
            str(staging),
            "--output",
            str(dest),
            "--scene-id",
            scene_id,
            "--layers",
            "roads,buildings",
            "--extent-json",
            str(dest / "extent.json"),
            "--pipeline-mode",
            "--road-width-scale",
            str(args.road_width_scale),
        ]
    )
    if rc != 0:
        print(f"error: build_city_usd failed rc={rc}", file=sys.stderr)
        return rc

    world = assemble_world(dest, scene_id)
    note = {
        "source_package": str(source),
        "scene_id": scene_id,
        "road_width_scale": float(args.road_width_scale),
        "buildings": "drop if intersecting scaled carriageway (footprint_after_roads)",
        "world": world.name,
    }
    (dest / "roads_scaled_meta.json").write_text(
        json.dumps(note, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"OK world={world}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
