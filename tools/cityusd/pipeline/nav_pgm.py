from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cityusd.nav_align_overlay import write_nav_align_overlay
from cityusd.nav_polys import collect_nav_polygons
from cityusd.osm_parse import parse_osm
from cityusd.pgm import rasterize_pgm
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

    _, origin, extent = load_extent_context(package_dir)
    step_cfg = load_step_config_ref(cfg, step, package_dir)
    outputs = step_cfg.get("outputs") or {}
    layer_flags = step_cfg.get("layers") or {}

    osm_path = _find_staged_osm(package_dir) or _resolve_input(cfg, "osm")
    if osm_path is None or not osm_path.is_file():
        raise FileNotFoundError(f"OSM not found for nav_pgm: {osm_path}")

    if not (package_dir / "inputs" / "build_data" / "osm" / osm_path.name).is_file():
        _stage_build_data(cfg, package_dir, osm_path)

    resolution_m = float(step_cfg.get("resolution_m", 1.0))
    log(f"[nav_pgm] rasterize @ {resolution_m} m from {osm_path.name}")

    osm = parse_osm(osm_path, origin)
    occupied, free = collect_nav_polygons(
        osm,
        use_buildings=bool(layer_flags.get("buildings", True)),
        use_water=bool(layer_flags.get("water", True)),
        use_roads_free=bool(layer_flags.get("roads", True)),
        simple_buildings=bool(step_cfg.get("simple_buildings", False)),
    )

    map_pgm = package_dir / str(outputs.get("map_pgm", "nav/map.pgm"))
    map_yaml = package_dir / str(outputs.get("map_yaml", "nav/map.yaml"))
    map_meta = package_dir / str(outputs.get("meta_json", "nav/map_meta.json"))

    rasterize_pgm(
        extent,
        occupied,
        free,
        resolution_m,
        map_pgm,
        map_yaml,
        map_meta,
        origin,
        range_source="pipeline_osm",
    )

    nav_usda = package_dir / "layers" / "nav.usda"
    nav_usda.parent.mkdir(parents=True, exist_ok=True)
    write_nav_layer(nav_usda, "./nav/map.pgm", "./nav/map.yaml")

    align_path = package_dir / "terrain" / "alignment.json"
    if align_path.is_file():
        hm_meta = package_dir / "terrain" / "heightmap_meta.json"
        ortho_meta = package_dir / "terrain" / "ortho_meta.json"
        write_terrain_alignment(
            align_path,
            scene_id=cfg.scene_id,
            origin=origin,
            extent=extent,
            heightmap_rel="./terrain/heightmap_ue.png" if (package_dir / "terrain" / "heightmap_ue.png").is_file() else None,
            ortho_rel="./terrain/ortho_ue.png" if (package_dir / "terrain" / "ortho_ue.png").is_file() else None,
            pgm_rel="./nav/map.pgm",
            cost_rel="./nav/cost.pgm",
            heightmap_meta_path=hm_meta if hm_meta.is_file() else None,
            ortho_meta_path=ortho_meta if ortho_meta.is_file() else None,
            pgm_meta_path=map_meta,
        )

    written = [
        str(map_pgm.relative_to(package_dir).as_posix()),
        str(map_yaml.relative_to(package_dir).as_posix()),
        str(map_meta.relative_to(package_dir).as_posix()),
        "nav/cost.pgm",
        "layers/nav.usda",
    ]

    align_cfg = step_cfg.get("align_overlay") or {}
    # Default ON for review builds; set enabled:false for production.
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

    log(f"[nav_pgm] ok occ={len(occupied)} free={len(free)} → {map_pgm.name}")
    return written
