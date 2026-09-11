# 中文说明：nav_octomap 步骤：OSM+DEM → CostMap/3D OctoMap（.bt + meta）。
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cityusd.crs import origin_utm
from cityusd.octomap3d.costmap_config_3d import load_config
from cityusd.octomap3d.pipeline_3d import build_costmap
from cityusd.pipeline.nav_pgm import _find_staged_osm
from cityusd.pipeline.osm_city_usd import _resolve_input, _stage_build_data
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.pipeline.terrain import _resolve_input as _resolve_terrain_input
from cityusd.pipeline.terrain import load_extent_context

LogFn = Callable[[str], None]


def _wgs84_bbox(extent_payload: dict) -> list[float] | None:
    box = extent_payload.get("wgs84") or {}
    keys = ("lon_west", "lat_south", "lon_east", "lat_north")
    if not all(k in box for k in keys):
        return None
    return [
        float(box["lon_west"]),
        float(box["lat_south"]),
        float(box["lon_east"]),
        float(box["lat_north"]),
    ]


def _resolve_dem(cfg: PipelineConfig, package_dir: Path, step_cfg: dict, log: LogFn) -> Path:
    dem_source = str(step_cfg.get("dem_source", "input")).strip().replace("\\", "/")
    if dem_source in ("input", "scene", ""):
        dem_path = _resolve_terrain_input(cfg, "dem")
        if dem_path is None or not dem_path.is_file():
            raise FileNotFoundError(f"DEM not found for nav_octomap (inputs.dem): {dem_path}")
        return dem_path

    cand = package_dir / dem_source
    if cand.is_file():
        return cand
    dem_path = _resolve_terrain_input(cfg, "dem")
    if dem_path and dem_path.is_file():
        log(f"[nav_octomap] WARN: {dem_source} missing; using scene DEM {dem_path.name}")
        return dem_path
    raise FileNotFoundError(f"DEM not found for nav_octomap: {dem_source}")


def _resolve_origin(
    step_cfg: dict,
    origin,
) -> list[float] | None:
    """功能：解析 OctoMap origin；默认与 CityUsd 场景原点对齐（UTM）。"""
    mode = step_cfg.get("origin", "scene")
    if mode is None or mode == "auto":
        return None
    if isinstance(mode, (list, tuple)) and len(mode) == 3:
        return [float(mode[0]), float(mode[1]), float(mode[2])]
    if str(mode).lower() in ("scene", "cityusd", "align"):
        east, north = origin_utm(origin.lon, origin.lat, origin.epsg)
        return [float(east), float(north), float(origin.height_m)]
    raise ValueError(
        "nav_octomap.origin must be 'scene', 'auto'/null, or [UTM_x, UTM_y, z]; "
        f"got {mode!r}"
    )


def run_nav_octomap(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    """功能：生成 CostMap/3D OctoMap（.bt）与 meta，并写 resolved 快照。"""
    step = cfg.step("nav_octomap")
    if step is None:
        raise RuntimeError("nav_octomap step missing from pipeline")

    extent_payload, origin, _extent = load_extent_context(package_dir)
    step_cfg = load_step_config_ref(cfg, step, package_dir)

    osm_path = _find_staged_osm(package_dir) or _resolve_input(cfg, "osm")
    if osm_path is None or not osm_path.is_file():
        raise FileNotFoundError(f"OSM not found for nav_octomap: {osm_path}")
    if not (package_dir / "inputs" / "build_data" / "osm" / osm_path.name).is_file():
        _stage_build_data(cfg, package_dir, osm_path)

    dem_path = _resolve_dem(cfg, package_dir, step_cfg, log)

    out_dir = cfg.costmap_3d_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Drop placeholder once real products exist.
    keep = out_dir / ".gitkeep"
    if keep.is_file():
        keep.unlink()

    out_prefix = str(step_cfg.get("out_prefix") or cfg.scene_id)
    resolution = float(step_cfg.get("resolution_m", step_cfg.get("resolution", 4.0)))

    bbox = step_cfg.get("bbox")
    if bbox is None and bool(step_cfg.get("clip_to_extent", True)):
        bbox = _wgs84_bbox(extent_payload)

    origin_xyz = _resolve_origin(step_cfg, origin)
    height = step_cfg.get("height") or {}

    overrides = {
        "osm": str(osm_path),
        "dem": str(dem_path),
        "out_dir": str(out_dir),
        "out_prefix": out_prefix,
        "resolution": resolution,
        "origin": origin_xyz,
        "bbox": bbox,
    }
    if height:
        overrides["height"] = height

    log(
        f"[nav_octomap] OctoMap @ {resolution:g} m from {osm_path.name} + {dem_path.name} "
        f"→ {cfg.scene_id}-CostMap/3D/"
    )
    if origin_xyz is not None:
        log(f"[nav_octomap] origin UTM=[{origin_xyz[0]:.3f}, {origin_xyz[1]:.3f}, {origin_xyz[2]:.3f}] (scene-aligned)")
    else:
        log("[nav_octomap] origin=auto (octomap data SW corner)")

    oct_cfg = load_config(None, overrides)
    result = build_costmap(oct_cfg)
    if not result.get("ok"):
        raise RuntimeError(f"nav_octomap build_costmap failed: {result}")

    outputs = result.get("outputs") or {}
    bt_path = Path(outputs["bt"])
    meta_path = Path(outputs["meta_json"])
    if not bt_path.is_file() or not meta_path.is_file():
        raise FileNotFoundError(f"nav_octomap missing outputs: {bt_path}, {meta_path}")

    # Enrich meta with CityUsd alignment hints (consumers / meta.json).
    try:
        stats = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        stats = dict(result.get("meta") or {})
    stats["cityusd"] = {
        "scene_id": cfg.scene_id,
        "utm_epsg": int(origin.epsg),
        "origin_wgs84": {
            "longitude": origin.lon,
            "latitude": origin.lat,
            "height_m": origin.height_m,
        },
        "origin_mode": step_cfg.get("origin", "scene"),
        "costmap_3d_rel": f"{cfg.scene_id}-CostMap/3D",
        "bt": bt_path.name,
        "meta_json": meta_path.name,
    }
    meta_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    written = [
        f"../{cfg.scene_id}-CostMap/3D/{bt_path.name}",
        f"../{cfg.scene_id}-CostMap/3D/{meta_path.name}",
    ]

    snap = {
        "step": "nav_octomap",
        "resolution_m": resolution,
        "out_prefix": out_prefix,
        "origin": origin_xyz,
        "bbox": bbox,
        "osm": str(osm_path),
        "dem": str(dem_path),
        "outputs": {"bt": bt_path.name, "meta_json": meta_path.name},
        "meta_summary": {
            "occupied_voxels_total": stats.get("occupied_voxels_total"),
            "utm_zone": stats.get("utm_zone"),
            "elapsed_s": stats.get("elapsed_s"),
        },
    }
    snap_path = package_dir / "configs" / "nav_octomap.resolved.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/nav_octomap.resolved.json")

    log(
        f"[nav_octomap] ok voxels={stats.get('occupied_voxels_total')} "
        f"→ {cfg.scene_id}-CostMap/3D/{bt_path.name}"
    )
    return written
