from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Callable

from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.pipeline.terrain import load_extent_context

LogFn = Callable[[str], None]

_CITY_LAYER_FILES = (
    "city_water.usdc",
    "city_vegetation.usdc",
    "city_roads.usdc",
    "city_buildings.usdc",
    "city_lamps.usdc",
    "city_signs.usdc",
)


def _resolve_input(cfg: PipelineConfig, key: str) -> Path | None:
    block = cfg.inputs.get(key) or {}
    raw = block.get("path")
    if not raw:
        return None
    p = Path(str(raw)).expanduser()
    if not p.is_absolute():
        cand = (cfg.project_root / p).resolve()
        if cand.is_file():
            return cand
    return p if p.is_file() else None


def _layers_from_config(step_cfg: dict) -> str:
    if step_cfg.get("build_layers"):
        return str(step_cfg["build_layers"])
    layer_map = step_cfg.get("layers") or {}
    names = []
    for key, on in (
        ("roads", layer_map.get("roads", True)),
        ("buildings", layer_map.get("buildings", True)),
        ("water", layer_map.get("water", True)),
        ("vegetation", layer_map.get("vegetation", True)),
        ("lamps", layer_map.get("lamps", True)),
        ("signs", layer_map.get("signs", True)),
    ):
        if on:
            names.append(key)
    return ",".join(names) if names else "roads,buildings,water,vegetation,lamps,signs"


def _stage_build_data(cfg: PipelineConfig, package_dir: Path, osm_path: Path) -> Path:
    staging = package_dir / "inputs" / "build_data"
    osm_dir = staging / "osm"
    osm_dir.mkdir(parents=True, exist_ok=True)
    dest = osm_dir / osm_path.name
    if not dest.exists() or dest.stat().st_mtime < osm_path.stat().st_mtime:
        shutil.copy2(osm_path, dest)

    assets_in = cfg.inputs.get("asset_library") or {}
    assets_raw = assets_in.get("path")
    if assets_raw:
        src = Path(str(assets_raw)).expanduser()
        if not src.is_absolute():
            src = (cfg.project_root / src).resolve()
        if src.is_dir():
            dst = staging / "assets"
            if dst.exists():
                if dst.is_symlink() or not dst.is_dir():
                    dst.unlink()
                else:
                    shutil.rmtree(dst)
            try:
                dst.symlink_to(src, target_is_directory=True)
            except OSError:
                shutil.copytree(src, dst, dirs_exist_ok=True)
    return staging


def _import_build_city_usd():
    tools_dir = Path(__file__).resolve().parents[2]
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import build_city_usd  # noqa: WPS433

    return build_city_usd


def run_osm_city_usd(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    step = cfg.step("osm_city_usd")
    if step is None:
        raise RuntimeError("osm_city_usd step missing from pipeline")

    load_extent_context(package_dir)
    step_cfg = load_step_config_ref(cfg, step, package_dir)

    osm_path = _resolve_input(cfg, "osm")
    if osm_path is None or not osm_path.is_file():
        raise FileNotFoundError(f"OSM input not found for osm_city_usd: {osm_path}")

    staging = _stage_build_data(cfg, package_dir, osm_path)
    layers = _layers_from_config(step_cfg)
    build_layers = [p.strip() for p in layers.split(",") if p.strip()]
    if step_cfg.get("layers"):
        for name, enabled in step_cfg["layers"].items():
            if not enabled and name in build_layers:
                build_layers = [x for x in build_layers if x != name]
    layers_arg = ",".join(build_layers)

    log(f"[osm_city_usd] build_city_usd layers={layers_arg} osm={osm_path.name}")
    build_city_usd = _import_build_city_usd()
    argv = [
        "--data",
        str(staging),
        "--output",
        str(package_dir),
        "--scene-id",
        cfg.scene_id,
        "--layers",
        layers_arg,
        "--extent-json",
        str(package_dir / "extent.json"),
        "--pipeline-mode",
    ]
    scale = step_cfg.get("road_width_scale")
    if scale is not None:
        argv.extend(["--road-width-scale", str(scale)])
    rc = build_city_usd.main(argv)
    if rc != 0:
        raise RuntimeError(f"build_city_usd exited with code {rc}")

    written: list[str] = []
    layers_dir = package_dir / "layers"
    outputs_cfg = step_cfg.get("outputs") or {}
    for stem, rel in outputs_cfg.items():
        path = package_dir / rel
        alt = path.with_suffix(".usda")
        if path.is_file():
            written.append(str(Path(rel).as_posix()))
        elif alt.is_file():
            written.append(str(alt.relative_to(package_dir).as_posix()))

    for name in _CITY_LAYER_FILES:
        p = layers_dir / name
        rel = f"layers/{name}"
        if p.is_file() and rel not in written:
            written.append(rel)
        alt = p.with_suffix(".usda")
        if alt.is_file():
            rel_a = f"layers/{alt.name}"
            if rel_a not in written:
                written.append(rel_a)

    stats_path = layers_dir / "city_build_stats.json"
    if stats_path.is_file():
        written.append("layers/city_build_stats.json")

    if not any("city_roads" in w for w in written):
        raise RuntimeError("osm_city_usd produced no city_roads layer")

    snap = package_dir / "configs" / "osm_city_usd.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/osm_city_usd.resolved.json")

    if (package_dir / "textures").is_dir():
        written.append("textures/")

    log(f"[osm_city_usd] ok → {len(written)} outputs")
    return written
