from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from cityusd.pipeline.assemble_world import run_assemble_world
from cityusd.pipeline.nav2_nature import run_nav2_nature
from cityusd.pipeline.nav_pgm import run_nav_pgm
from cityusd.pipeline.osm_city_usd import run_osm_city_usd
from cityusd.pipeline.osm_labels import run_osm_labels
from cityusd.pipeline.overlay import run_overlay
from cityusd.pipeline.package_zip import run_package_zip
from cityusd.pipeline.terrain import run_terrain
from cityusd.pipeline.resolve_extent import resolve_extent, write_extent_json
from cityusd.pipeline.package_backup import prepare_release_run
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref, write_manifest

LogFn = Callable[[str], None]


def _log_default(msg: str) -> None:
    print(msg, flush=True)


def _input_hash(
    cfg: PipelineConfig,
    package_dir: Optional[Path] = None,
    step_name: Optional[str] = None,
) -> str:
    blob: dict = {
        "frame": cfg.frame,
        "inputs": cfg.inputs,
        "scene_id": cfg.scene_id,
    }
    if step_name and package_dir is not None:
        step = cfg.step(step_name)
        if step and (step.config_ref or step.config):
            blob["step_config"] = load_step_config_ref(cfg, step, package_dir)
    if package_dir is not None and (package_dir / "extent.json").is_file():
        if step_name in (None, "terrain", "nav_pgm", "nav2_nature", "osm_city_usd", "osm_labels"):
            blob["extent"] = json.loads((package_dir / "extent.json").read_text(encoding="utf-8"))
    return "sha256:" + hashlib.sha256(
        json.dumps(blob, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:16]


def run_resolve_extent(cfg: PipelineConfig, package_dir: Path, log: LogFn = _log_default) -> dict:
    log("[resolve_extent] computing spatial contract...")
    payload = resolve_extent(
        frame=cfg.frame,
        inputs=cfg.inputs,
        project_root=cfg.project_root,
        input_dirs=[cfg.input_dir()],
    )
    out = package_dir / "extent.json"
    write_extent_json(out, payload)
    for w in payload.get("warnings") or []:
        log(f"[resolve_extent] WARN: {w}")
    log(
        f"[resolve_extent] ok → {out.name} "
        f"({payload['local_m']['width_x']/1000:.2f} x {payload['local_m']['height_y']/1000:.2f} km local)"
    )
    return payload


def _stub_step(name: str, cfg: PipelineConfig, package_dir: Path, log: LogFn) -> None:
    step = cfg.step(name)
    if step is None:
        return
    step_cfg = load_step_config_ref(cfg, step, package_dir) if step.config_ref or step.config else {}
    configs_dir = package_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    marker = configs_dir / f"{name}.pending.json"
    marker.write_text(
        json.dumps({"step": name, "status": "not_implemented_m0", "config": step_cfg}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    log(f"[{name}] skipped (M0 stub — config written to {marker.relative_to(package_dir)})")


def _run_terrain_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_terrain(cfg, package_dir, log)
    return None, outputs


def _run_osm_city_usd_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_osm_city_usd(cfg, package_dir, log)
    return None, outputs


def _run_osm_labels_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_osm_labels(cfg, package_dir, log)
    return None, outputs


def _run_nav_pgm_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_nav_pgm(cfg, package_dir, log)
    return None, outputs


def _run_nav2_nature_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_nav2_nature(cfg, package_dir, log)
    return None, outputs


def _run_overlay_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_overlay(cfg, package_dir, log)
    return None, outputs


def _run_assemble_world_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_assemble_world(cfg, package_dir, log)
    return None, outputs


def _run_package_zip_step(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> tuple[None, list[str]]:
    outputs = run_package_zip(cfg, package_dir, log)
    return None, outputs


STEP_RUNNERS = {
    "resolve_extent": lambda cfg, pkg, log: (run_resolve_extent(cfg, pkg, log), ["extent.json"]),
    "terrain": _run_terrain_step,
    "osm_city_usd": _run_osm_city_usd_step,
    "osm_labels": _run_osm_labels_step,
    "nav_pgm": _run_nav_pgm_step,
    "nav2_nature": _run_nav2_nature_step,
    "overlay": _run_overlay_step,
    "assemble_world": _run_assemble_world_step,
    "package_zip": _run_package_zip_step,
}


def run_pipeline(
    cfg: PipelineConfig,
    *,
    only: Optional[list[str]] = None,
    resume: bool = False,
    log: LogFn = _log_default,
) -> Path:
    prepare_release_run(cfg, log)

    cfg.ensure_dirs()
    package_dir = cfg.package_dir()
    package_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = package_dir / "manifest.json"
    manifest: dict = {"schema_version": cfg.schema_version, "scene_id": cfg.scene_id, "steps": {}}
    if resume and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    requested = set(only) if only else None

    for step in cfg.steps:
        if not step.enabled:
            continue
        if requested is not None and step.step not in requested:
            continue

        ih = _input_hash(cfg, package_dir, step.step)
        prev = (manifest.get("steps") or {}).get(step.step) or {}
        if resume and prev.get("status") == "ok" and prev.get("input_hash") == ih:
            log(f"[{step.step}] resume skip (unchanged)")
            continue

        runner = STEP_RUNNERS.get(step.step)
        t0 = datetime.now(timezone.utc).isoformat()
        try:
            if runner is None:
                _stub_step(step.step, cfg, package_dir, log)
                status = "stub"
                outputs: list[str] = [f"configs/{step.step}.pending.json"]
            else:
                result = runner(cfg, package_dir, log)
                if isinstance(result, tuple):
                    _, outputs = result
                    if outputs is None:
                        outputs = []
                else:
                    outputs = ["extent.json"] if step.step == "resolve_extent" else []
                status = "ok"

            manifest.setdefault("steps", {})[step.step] = {
                "status": status,
                "started_at": t0,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "input_hash": ih,
                "outputs": outputs,
            }
        except Exception as exc:
            manifest.setdefault("steps", {})[step.step] = {
                "status": "failed",
                "started_at": t0,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "input_hash": ih,
                "error": str(exc),
            }
            write_manifest(manifest_path, manifest)
            if str(cfg.runtime.get("on_step_fail", "stop")).lower() != "continue":
                raise
            log(f"[{step.step}] FAILED: {exc}")

    write_manifest(manifest_path, manifest)

    # Copy pipeline snapshot for reproducibility
    snap = package_dir / "pipeline.yaml"
    if cfg.source_path.is_file() and not snap.exists():
        snap.write_text(cfg.source_path.read_text(encoding="utf-8"), encoding="utf-8")

    meta_path = package_dir / "meta.json"
    meta: dict = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    stats_path = package_dir / "layers" / "city_build_stats.json"
    if stats_path.is_file() and "city_build" not in meta:
        try:
            meta["city_build"] = json.loads(stats_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if meta.get("spec_version") != "1.0":
        meta.update(
            {
                "spec_version": cfg.schema_version,
                "scene_id": cfg.scene_id,
                "title": cfg.scene_title,
                "layout": cfg.output_layout,
                "package_dir": str(package_dir),
            }
        )
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Scene-level alignment JSON (USD + CostMap consumers).
    try:
        from cityusd.scene_layout import write_alignment_meta
        from cityusd.pipeline.terrain import load_extent_context

        extent_payload, origin, extent = load_extent_context(package_dir)
        connected_meta = cfg.costmap_2d_dir() / "connected" / "map_meta.json"
        resolution: dict = {"meters_per_unit_usd": 0.01}
        if connected_meta.is_file():
            try:
                cm = json.loads(connected_meta.read_text(encoding="utf-8"))
                if "resolution_m" in cm:
                    resolution["nav_resolution_m"] = float(cm["resolution_m"])
                elif "resolution" in cm:
                    resolution["nav_resolution_m"] = float(cm["resolution"])
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        write_alignment_meta(
            cfg.scene_root() / "scene_alignment.json",
            scene_id=cfg.scene_id,
            origin_wgs84={"lon": origin.lon, "lat": origin.lat, "height_m": origin.height_m},
            extent_m=extent.to_json(),
            crs_epsg=int(origin.epsg),
            resolution=resolution,
            usd_rel="./output/USD",
            costmap_2d_rel="./output/CostMap/2D",
            costmap_3d_rel="./output/CostMap/3D",
        )
        # Mirror next to CostMap for consumers that only mount CostMap.
        write_alignment_meta(
            cfg.costmap_2d_dir() / "scene_alignment.json",
            scene_id=cfg.scene_id,
            origin_wgs84={"lon": origin.lon, "lat": origin.lat, "height_m": origin.height_m},
            extent_m=extent.to_json(),
            crs_epsg=int(origin.epsg),
            resolution=resolution,
            usd_rel="../USD",
            costmap_2d_rel="./",
            costmap_3d_rel="../3D",
        )
    except Exception as exc:
        log(f"[scene_alignment] skip: {exc}")

    log(f"=== pipeline done → {cfg.scene_root()}")
    return package_dir
