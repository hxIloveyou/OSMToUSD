from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cityusd.dem_nature import build_nav2_nature_from_dem_utm
from cityusd.nav2_paths import NAV2_DEM, NAV2_NATURE
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.pipeline.terrain import _resolve_input, load_extent_context

LogFn = Callable[[str], None]


def run_nav2_nature(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    step = cfg.step("nav2_nature")
    if step is None:
        raise RuntimeError("nav2_nature step missing from pipeline")

    step_cfg = load_step_config_ref(cfg, step, package_dir)
    outputs = step_cfg.get("outputs") or {}
    extent_payload, origin, extent = load_extent_context(package_dir)

    dem_rel = str(step_cfg.get("dem_source", "terrain/dem_utm.tif"))
    dem_utm = package_dir / dem_rel
    dem_optional = bool(step_cfg.get("optional", False))

    if not dem_utm.is_file():
        dem_path = _resolve_input(cfg, "dem")
        if dem_path and dem_path.is_file():
            log(f"[nav2_nature] WARN: {dem_rel} missing; run terrain step first (source DEM: {dem_path.name})")
        if dem_optional:
            log("[nav2_nature] skip — no terrain/dem_utm.tif (optional)")
            return []
        raise FileNotFoundError(
            f"nav2_nature requires {dem_rel} from terrain step; run terrain first"
        )

    name = str(step_cfg.get("name", "dem"))
    if name == "dem":
        src_dem = _resolve_input(cfg, "dem")
        if src_dem is not None:
            name = src_dem.stem

    nature_dir_rel = str(outputs.get("nature_dir", NAV2_NATURE)).replace("\\", "/").lstrip("./")
    dem_dir_rel = str(outputs.get("dem_dir", NAV2_DEM)).replace("\\", "/").lstrip("./")
    if nature_dir_rel.startswith("nav2/"):
        nature_dir_rel = nature_dir_rel[len("nav2/") :]
    if dem_dir_rel.startswith("nav2/"):
        dem_dir_rel = dem_dir_rel[len("nav2/") :]
    max_slope = float(step_cfg.get("max_slope", 0.35))
    cliff_slope = float(step_cfg.get("cliff_slope", 0.70))

    cost_root = cfg.costmap_2d_dir()
    cost_root.mkdir(parents=True, exist_ok=True)
    log(f"[nav2_nature] BMP + slope PGM from {dem_utm.name} → {cfg.scene_id}-CostMap/2D/{nature_dir_rel}/")
    result = build_nav2_nature_from_dem_utm(
        dem_utm,
        cost_root,
        extent=extent,
        origin=origin,
        name=name,
        max_slope=max_slope,
        cliff_slope=cliff_slope,
        nature_dir_rel=nature_dir_rel,
        dem_dir_rel=dem_dir_rel,
    )
    log(
        f"[nav2_nature] ok resolution={result['resolution_m']:.3f}m "
        f"scale={result['scale']:.3f} free={result['free_px']} occ={result['occupied_px']}"
    )

    snap = package_dir / "configs" / "nav2_nature.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    prefix = cfg.costmap_rel_prefix()
    written = [f"{prefix}/{o}" for o in result["outputs"]]
    written.append("configs/nav2_nature.resolved.json")
    return written
