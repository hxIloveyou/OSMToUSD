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
from cityusd.pgm import rasterize_pgm, write_nav2_yaml_bundle
from cityusd.pipeline.osm_city_usd import _resolve_input, _stage_build_data
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.pipeline.terrain import load_extent_context
from cityusd.rasters import write_terrain_alignment
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

    out_rel = str(outputs.get("out_dir", NAV2_CONNECTED))
    out_dir = package_dir / out_rel
    map_pgm = package_dir / str(outputs.get("map_pgm", NAV2_CONNECTED_PGM))
    map_local_yaml = package_dir / str(outputs.get("map_local_yaml", NAV2_CONNECTED_MAP_LOCAL))
    map_meta = package_dir / str(outputs.get("meta_json", NAV2_CONNECTED_META))

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

    connected_note = {
        "mode": "connected",
        "resolution_m": resolution_m,
        "free_all_touched": True,
        "binary_occupancy": True,
        "cost_same_as_map": True,
        "road_source": "motor_carriageway_polygons (flat cap, round join, no hierarchy cut)",
        "occupied_polys": len(occupied),
        "free_polys": len(free),
    }
    (out_dir / "nav_connected_meta.json").write_text(
        json.dumps(connected_note, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "README.txt").write_text(
        "Default nav2 connected occupancy (pipeline nav_pgm, schema v0.3).\n"
        "Binary map; no unknown(205). Use map_local.yaml for Nav2/USD alignment.\n",
        encoding="utf-8",
    )

    nav_usda = package_dir / "layers" / "nav.usda"
    nav_usda.parent.mkdir(parents=True, exist_ok=True)
    write_nav_layer(nav_usda, f"./{NAV2_CONNECTED}/map.pgm", f"./{NAV2_CONNECTED}/map_local.yaml")

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
            pgm_rel=f"./{NAV2_CONNECTED_PGM}",
            cost_rel=f"./{NAV2_CONNECTED_COST}",
            heightmap_meta_path=hm_meta if hm_meta.is_file() else None,
            ortho_meta_path=ortho_meta if ortho_meta.is_file() else None,
            pgm_meta_path=map_meta,
        )

    written = [
        str(map_pgm.relative_to(package_dir).as_posix()),
        str(map_local_yaml.relative_to(package_dir).as_posix()),
        f"{NAV2_CONNECTED}/map.yaml",
        f"{NAV2_CONNECTED}/valhalla_origin.yaml",
        str(map_meta.relative_to(package_dir).as_posix()),
        NAV2_CONNECTED_COST,
        f"{NAV2_CONNECTED}/nav_connected_meta.json",
        "layers/nav.usda",
    ]

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
            "[nav_pgm] debug align overlay → debug/nav_align/ "
            "(NOT in World; disable align_overlay.enabled for production)"
        )
    else:
        log("[nav_pgm] align_overlay disabled (production mode)")

    snap = package_dir / "configs" / "nav_pgm.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/nav_pgm.resolved.json")

    log(f"[nav_pgm] ok occ={len(occupied)} free={len(free)} → {out_rel}/")
    return written
