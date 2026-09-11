# 中文说明：nav_pgm 步骤：OSM → CostMap/2D 占据图、软边与对齐 debug 叠加。
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cityusd.nav2_paths import (
    NAV2_CONNECTED,
    NAV2_CONNECTED_COST,
    NAV2_CONNECTED_MAP_LOCAL,
    NAV2_CONNECTED_META,
    NAV2_CONNECTED_PGM,
)
from cityusd.nav_align_overlay import write_nav_align_overlay
from cityusd.nav_polys import collect_nav_polygons_connected
from cityusd.osm_parse import parse_osm
from cityusd.pgm import rasterize_pgm, write_nav2_yaml_bundle, write_soft_edge_pgm
from cityusd.pipeline.osm_city_usd import _resolve_input, _stage_build_data
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.pipeline.terrain import load_extent_context
from cityusd.rasters import write_terrain_alignment
from cityusd.scene_layout import costmap_rel_from_usd
from cityusd.usd_write import write_nav_layer

LogFn = Callable[[str], None]


def _find_staged_osm(package_dir: Path) -> Path | None:
    staging = package_dir / "inputs" / "build_data" / "osm"
    if staging.is_dir():
        for ext in ("*.osm.pbf", "*.osm"):
            hits = sorted(staging.glob(ext))
            if hits:
                return hits[0]
    return None


def run_nav_pgm(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    """功能：生成 CostMap/2D 占据图与相关 yaml/软边。"""
    step = cfg.step("nav_pgm")
    if step is None:
        raise RuntimeError("nav_pgm step missing from pipeline")

    extent_payload, origin, extent = load_extent_context(package_dir)
    step_cfg = load_step_config_ref(cfg, step, package_dir)
    outputs = step_cfg.get("outputs") or {}

    osm_path = _find_staged_osm(package_dir) or _resolve_input(cfg, "osm")
    if osm_path is None or not osm_path.is_file():
        raise FileNotFoundError(f"OSM not found for nav_pgm: {osm_path}")

    if not (package_dir / "inputs" / "build_data" / "osm" / osm_path.name).is_file():
        _stage_build_data(cfg, package_dir, osm_path)

    resolution_m = float(step_cfg.get("resolution_m", 1.0))
    mode = str(step_cfg.get("mode", "connected"))
    log(f"[nav_pgm] {mode} rasterize @ {resolution_m} m from {osm_path.name}")

    osm = parse_osm(osm_path, origin)
    occupied, free = collect_nav_polygons_connected(
        osm,
        simple_buildings=bool(step_cfg.get("simple_buildings", False)),
    )

    cost_root = cfg.costmap_2d_dir()
    cost_root.mkdir(parents=True, exist_ok=True)
    cm_prefix = cfg.costmap_rel_prefix()
    out_rel = str(outputs.get("out_dir", NAV2_CONNECTED)).replace("\\", "/").lstrip("./")
    if out_rel.startswith("nav2/"):
        out_rel = out_rel[len("nav2/") :]
    out_dir = cost_root / out_rel

    def _cost_path(key: str, default: str) -> Path:
        rel = str(outputs.get(key, default)).replace("\\", "/").lstrip("./")
        if rel.startswith("nav2/"):
            rel = rel[len("nav2/") :]
        return cost_root / rel

    map_pgm = _cost_path("map_pgm", NAV2_CONNECTED_PGM)
    map_local_yaml = _cost_path("map_local_yaml", NAV2_CONNECTED_MAP_LOCAL)
    map_meta = _cost_path("meta_json", NAV2_CONNECTED_META)
    cost_pgm = _cost_path("cost_pgm", NAV2_CONNECTED_COST)

    rasterize_pgm(
        extent,
        occupied,
        free,
        resolution_m,
        map_pgm,
        map_local_yaml,
        map_meta,
        origin,
        range_source="connected_osm",
        free_all_touched=True,
        binary_occupancy=True,
        cost_same_as_map=True,
    )

    write_nav2_yaml_bundle(
        out_dir,
        extent=extent,
        extent_payload=extent_payload,
        origin=origin,
        resolution_m=resolution_m,
        scene_id=cfg.scene_id,
    )

    soft_cfg = step_cfg.get("soft_edge") or {}
    soft_enabled = bool(soft_cfg.get("enabled", True))
    soft_radius_m = float(soft_cfg.get("radius_m", 2.0))
    soft_rel = str(soft_cfg.get("output") or outputs.get("map_soft_pgm") or f"{out_rel}/map_soft.pgm")
    soft_rel = soft_rel.replace("\\", "/").lstrip("./")
    if soft_rel.startswith("nav2/"):
        soft_rel = soft_rel[len("nav2/") :]
    soft_pgm = cost_root / soft_rel
    if soft_enabled:
        write_soft_edge_pgm(
            map_pgm,
            soft_pgm,
            resolution_m=resolution_m,
            radius_m=soft_radius_m,
        )
        log(f"[nav_pgm] soft-edge map → {soft_rel} (radius={soft_radius_m:g} m)")

    connected_note = {
        "mode": "connected",
        "resolution_m": resolution_m,
        "free_all_touched": True,
        "binary_occupancy": True,
        "cost_same_as_map": True,
        "road_source": "motor_carriageway_polygons (flat cap, round join, no hierarchy cut)",
        "occupied_polys": len(occupied),
        "free_polys": len(free),
        "costmap_root": f"{cfg.scene_id}-CostMap/2D",
        "soft_edge": {
            "enabled": soft_enabled,
            "radius_m": soft_radius_m,
            "map_soft_pgm": soft_rel if soft_enabled else None,
        },
    }
    (out_dir / "nav_connected_meta.json").write_text(
        json.dumps(connected_note, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "README.txt").write_text(
        f"Connected occupancy under SceneData/{{id}}/output/{cfg.scene_id}-CostMap/2D/connected/.\n"
        "Binary map.pgm for Nav2; map_soft.pgm is visualization anti-alias (not for planning).\n",
        encoding="utf-8",
    )

    if map_meta.is_file():
        try:
            meta_payload = json.loads(map_meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta_payload = {}
        if soft_enabled:
            meta_payload["map_soft_pgm"] = soft_pgm.name
            meta_payload["soft_edge_radius_m"] = soft_radius_m
        map_meta.write_text(json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pgm_from_usd = costmap_rel_from_usd(map_pgm.relative_to(cost_root).as_posix(), cfg.scene_id)
    yaml_from_usd = costmap_rel_from_usd(map_local_yaml.relative_to(cost_root).as_posix(), cfg.scene_id)
    cost_from_usd = costmap_rel_from_usd(cost_pgm.relative_to(cost_root).as_posix(), cfg.scene_id)

    nav_usda = package_dir / "layers" / "nav.usda"
    nav_usda.parent.mkdir(parents=True, exist_ok=True)
    write_nav_layer(nav_usda, pgm_from_usd, yaml_from_usd, cost_from_usd)

    align_path = package_dir / "terrain" / "alignment.json"
    if align_path.is_file():
        hm_meta = package_dir / "terrain" / "heightmap_meta.json"
        ortho_meta = package_dir / "terrain" / "ortho_meta.json"
        write_terrain_alignment(
            align_path,
            scene_id=cfg.scene_id,
            origin=origin,
            extent=extent,
            heightmap_rel="./terrain/heightmap_ue.png"
            if (package_dir / "terrain" / "heightmap_ue.png").is_file()
            else None,
            ortho_rel="./terrain/ortho_ue.png"
            if (package_dir / "terrain" / "ortho_ue.png").is_file()
            else None,
            pgm_rel=pgm_from_usd,
            cost_rel=cost_from_usd,
            heightmap_meta_path=hm_meta if hm_meta.is_file() else None,
            ortho_meta_path=ortho_meta if ortho_meta.is_file() else None,
            pgm_meta_path=map_meta,
        )

    written = [
        f"{cm_prefix}/{map_pgm.relative_to(cost_root).as_posix()}",
        f"{cm_prefix}/{map_local_yaml.relative_to(cost_root).as_posix()}",
        f"{cm_prefix}/{out_rel}/map.yaml",
        f"{cm_prefix}/{out_rel}/valhalla_origin.yaml",
        f"{cm_prefix}/{map_meta.relative_to(cost_root).as_posix()}",
        f"{cm_prefix}/{cost_pgm.relative_to(cost_root).as_posix()}",
        f"{cm_prefix}/{out_rel}/nav_connected_meta.json",
        "layers/nav.usda",
    ]
    if soft_enabled and soft_pgm.is_file():
        written.append(f"{cm_prefix}/{soft_pgm.relative_to(cost_root).as_posix()}")

    align_cfg = step_cfg.get("align_overlay") or {}
    if bool(align_cfg.get("enabled", True)):
        overlay_outs = write_nav_align_overlay(
            package_dir,
            map_pgm=map_pgm,
            map_meta_path=map_meta,
            extent=extent,
            enabled=True,
            max_preview_side=int(align_cfg.get("max_preview_side", 4096)),
            z_cm=float(align_cfg.get("z_cm", 50.0)),
        )
        written.extend(overlay_outs)
        log(
            f"[nav_pgm] debug align overlay → {cfg.scene_id}-USD/debug/nav_align/ "
            "(NOT in World; disable align_overlay.enabled for production)"
        )
    else:
        log("[nav_pgm] align_overlay disabled (production mode)")

    snap = package_dir / "configs" / "nav_pgm.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/nav_pgm.resolved.json")

    log(f"[nav_pgm] ok occ={len(occupied)} free={len(free)} → {cfg.scene_id}-CostMap/2D/{out_rel}/")
    return written
