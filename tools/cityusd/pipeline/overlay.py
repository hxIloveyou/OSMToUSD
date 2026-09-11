# 中文说明：overlay 步骤：场景描述 → equipment/infrastructure 等 overlay USD。
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cityusd.package import OVERLAY_LAYERS, write_all_overlays, write_empty_overlay
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref

LogFn = Callable[[str], None]


def _resolve_input(cfg: PipelineConfig, key: str) -> Path | None:
    block = cfg.inputs.get(key) or {}
    raw = block.get("path")
    if not raw:
        return None
    p = Path(str(raw)).expanduser()
    if p.is_absolute():
        return p if p.is_file() else None
    candidates = [
        (cfg.project_root / p).resolve(),
        (cfg.input_dir() / p).resolve(),
        (cfg.input_dir() / p.name).resolve(),
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def run_overlay(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    """功能：根据场景描述生成 overlay USD（可跳过）。"""
    step = cfg.step("overlay")
    if step is None:
        raise RuntimeError("overlay step missing from pipeline")

    step_cfg = load_step_config_ref(cfg, step, package_dir)
    outputs_cfg = step_cfg.get("outputs") or {}
    skip_if_no_description = bool(step_cfg.get("skip_if_no_description", True))

    description = _resolve_input(cfg, "scene_description")
    if description is None and skip_if_no_description:
        log("[overlay] no scene_description — writing empty overlay layers")
    elif description is not None:
        log(f"[overlay] description registered (prims stay empty): {description.name}")

    overlay_dir = package_dir / "overlay"
    written: list[str] = []

    if outputs_cfg:
        overlay_dir.mkdir(parents=True, exist_ok=True)
        for key, rel in outputs_cfg.items():
            rel_path = Path(str(rel))
            filename = rel_path.name
            prim_name = next((name for fn, name in OVERLAY_LAYERS if fn == filename), key.title())
            dest = package_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_empty_overlay(dest, prim_name)
            written.append(str(rel_path.as_posix()))
    else:
        for path in write_all_overlays(overlay_dir):
            written.append(str(path.relative_to(package_dir).as_posix()))

    sources_path = package_dir / "sources_manifest.json"
    sources: dict = {}
    if sources_path.is_file():
        try:
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sources = {}

    descriptions: list[str] = list(sources.get("descriptions") or [])
    if description is not None:
        desc_str = str(description)
        if desc_str not in descriptions:
            descriptions.append(desc_str)
    sources["descriptions"] = descriptions

    osm = _resolve_input(cfg, "osm")
    if osm is not None:
        sources.setdefault("osm", str(osm))
    dem = _resolve_input(cfg, "dem")
    if dem is not None:
        sources.setdefault("dem", str(dem))
    ortho = _resolve_input(cfg, "ortho")
    if ortho is not None:
        sources.setdefault("imagery", str(ortho))
    assets = cfg.inputs.get("asset_library") or {}
    assets_raw = assets.get("path")
    if assets_raw:
        ap = Path(str(assets_raw)).expanduser()
        if not ap.is_absolute():
            ap = (cfg.project_root / ap).resolve()
        if ap.is_dir():
            sources.setdefault("asset_library", str(ap))

    sources_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("sources_manifest.json")

    snap = package_dir / "configs" / "overlay.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/overlay.resolved.json")

    log(f"[overlay] ok → {len(written)} files")
    return written
