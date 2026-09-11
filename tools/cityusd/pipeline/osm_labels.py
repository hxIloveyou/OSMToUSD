# 中文说明：osm_labels 步骤：OSM 属性按网格分片写入 catalog（默认不进 World）。
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Callable

from cityusd.osm_parse import OsmData, OsmNode, OsmWay, parse_osm
from cityusd.pipeline.osm_city_usd import _resolve_input, _stage_build_data
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.pipeline.terrain import load_extent_context
from cityusd.types import ExtentM

LogFn = Callable[[str], None]

OSM_ATTR_SCHEMA = {
    "schema_version": "0.2",
    "description": "Sharded OSM feature catalog for runtime API / UE point pick",
    "feature_fields": {
        "osm_id": "int",
        "osm_type": "way|node",
        "category": "building|road|water|vegetation|tree|other",
        "tags": "object",
        "centroid_m": "[x, y] local meters",
        "catalog_shard": "lod0_{ix}_{iy}",
    },
    "shard_naming": "lod0_{ix:+05d}_{iy:+05d}.json",
    "grid": {"align_with": "LOD0", "origin": "extent-local", "row_axis": "south"},
}


def _category(tags: dict[str, str]) -> str:
    if "building" in tags:
        return "building"
    if "highway" in tags:
        return "road"
    if tags.get("natural") == "water" or "waterway" in tags or tags.get("landuse") == "reservoir":
        return "water"
    if tags.get("natural") == "tree":
        return "tree"
    if tags.get("natural") in {"wood"} or tags.get("landuse") in {"forest", "grass", "meadow"}:
        return "vegetation"
    if tags.get("leisure") == "park":
        return "vegetation"
    return "other"


def _centroid_way(way: OsmWay) -> tuple[float, float]:
    xs = [p[0] for p in way.coords_m]
    ys = [p[1] for p in way.coords_m]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def shard_id_for_xy(x_m: float, y_m: float, extent: ExtentM, cell_size_m: float) -> str:
    if cell_size_m <= 0:
        raise ValueError("cell_size_m must be positive")
    ix = int(math.floor((x_m - extent.west) / cell_size_m))
    iy = int(math.floor((extent.north - y_m) / cell_size_m))
    return f"lod0_{ix:+05d}_{iy:+05d}"


def _feature_record(
    osm_id: int,
    osm_type: str,
    tags: dict[str, str],
    centroid_m: tuple[float, float],
    shard: str,
) -> dict:
    return {
        "osm_id": int(osm_id),
        "osm_type": osm_type,
        "category": _category(tags),
        "tags": dict(tags),
        "centroid_m": [float(centroid_m[0]), float(centroid_m[1])],
        "catalog_shard": shard,
    }


def extract_features(osm: OsmData, extent: ExtentM, cell_size_m: float) -> dict[str, list[dict]]:
    shards: dict[str, list[dict]] = defaultdict(list)
    for way in osm.ways:
        if not way.tags:
            continue
        cat = _category(way.tags)
        if cat == "other":
            continue
        cx, cy = _centroid_way(way)
        sid = shard_id_for_xy(cx, cy, extent, cell_size_m)
        shards[sid].append(_feature_record(way.osm_id, "way", way.tags, (cx, cy), sid))
    for node in osm.nodes:
        if not node.tags:
            continue
        cat = _category(node.tags)
        if cat == "other":
            continue
        sid = shard_id_for_xy(node.xy_m[0], node.xy_m[1], extent, cell_size_m)
        shards[sid].append(_feature_record(node.osm_id, "node", node.tags, node.xy_m, sid))
    return shards


def run_osm_labels(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    """功能：写出 OSM 属性分片 catalog。"""
    step = cfg.step("osm_labels")
    if step is None:
        raise RuntimeError("osm_labels step missing from pipeline")

    _, origin, extent = load_extent_context(package_dir)
    step_cfg = load_step_config_ref(cfg, step, package_dir)
    outputs = step_cfg.get("outputs") or {}
    grid = step_cfg.get("shard_grid") or {}
    cell_size_m = float(grid.get("cell_size_m", 200))

    osm_path = _resolve_input(cfg, "osm")
    if osm_path is None or not osm_path.is_file():
        staged = package_dir / "inputs" / "build_data" / "osm"
        if staged.is_dir():
            hits = sorted(staged.glob("*.osm*"))
            osm_path = hits[0] if hits else None
    if osm_path is None or not osm_path.is_file():
        raise FileNotFoundError("OSM not found for osm_labels")

    _stage_build_data(cfg, package_dir, osm_path)
    log(f"[osm_labels] shard grid {cell_size_m}m from {osm_path.name}")

    osm = parse_osm(osm_path, origin)
    shards = extract_features(osm, extent, cell_size_m)

    shards_dir = package_dir / str(outputs.get("shards_dir", "catalog/shards/"))
    shards_dir.mkdir(parents=True, exist_ok=True)
    for old in shards_dir.glob("lod0_*.json"):
        old.unlink()

    manifest_shards = []
    total = 0
    for sid in sorted(shards.keys()):
        features = shards[sid]
        fname = f"{sid}.json"
        payload = {
            "schema_version": "0.2",
            "shard_id": sid,
            "cell_size_m": cell_size_m,
            "feature_count": len(features),
            "features": features,
        }
        (shards_dir / fname).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        manifest_shards.append(
            {
                "shard_id": sid,
                "file": f"catalog/shards/{fname}",
                "feature_count": len(features),
            }
        )
        total += len(features)

    index_path = package_dir / str(outputs.get("index", "catalog/index/shard_manifest.json"))
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_payload = {
        "schema_version": "0.2",
        "scene_id": cfg.scene_id,
        "cell_size_m": cell_size_m,
        "align_with": grid.get("align_with", "LOD0"),
        "shard_count": len(manifest_shards),
        "feature_count": total,
        "runtime_api": step_cfg.get("runtime_api", {}),
        "compose_into_world": bool(step_cfg.get("compose_into_world", False)),
        "shards": manifest_shards,
    }
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    schema_path = package_dir / str(outputs.get("schema", "catalog/osm_attr_schema.json"))
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema = dict(OSM_ATTR_SCHEMA)
    schema["cell_size_m"] = cell_size_m
    schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    written = [
        str(index_path.relative_to(package_dir).as_posix()),
        str(schema_path.relative_to(package_dir).as_posix()),
        f"catalog/shards/ ({len(manifest_shards)} files)",
    ]

    snap = package_dir / "configs" / "osm_labels.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/osm_labels.resolved.json")

    log(f"[osm_labels] ok {total} features → {len(manifest_shards)} shards")
    return written
