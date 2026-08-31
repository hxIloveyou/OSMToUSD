from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("PyYAML required: pip install pyyaml") from exc


SCHEMA_VERSION = "0.2"


def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for key, val in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Pipeline config must be a mapping: {path}")
    return data


def _resolve_extends(data: dict, base_dir: Path) -> dict:
    extends = data.pop("extends", None) or []
    if isinstance(extends, str):
        extends = [extends]
    merged: dict = {}
    for rel in extends:
        preset_path = (base_dir / rel).resolve()
        if not preset_path.is_file():
            raise FileNotFoundError(f"Preset not found: {preset_path}")
        preset = _load_yaml(preset_path)
        merged = _deep_merge(merged, _resolve_extends(preset, preset_path.parent))
    return _deep_merge(merged, data)


@dataclass
class StepConfig:
    step: str
    enabled: bool = True
    depends_on: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    config_ref: Optional[str] = None


def _find_project_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "configs").is_dir() and (p / "presets").is_dir():
            return p
    return start.parent


@dataclass
class PipelineConfig:
    schema_version: str
    scene_id: str
    scene_title: str
    scene_id_pattern: str
    frame: dict[str, Any]
    inputs: dict[str, Any]
    output_dir: Path
    output_layout: str
    steps: list[StepConfig]
    runtime: dict[str, Any]
    raw: dict[str, Any]
    source_path: Path
    project_root: Path

    def package_dir(self) -> Path:
        return self.output_dir / self.scene_id

    def step(self, name: str) -> Optional[StepConfig]:
        for s in self.steps:
            if s.step == name:
                return s
        return None

    def enabled_steps(self) -> list[StepConfig]:
        return [s for s in self.steps if s.enabled]


def _ensure_scene_id(scene: dict) -> str:
    sid = str(scene.get("id") or "").strip()
    if sid:
        return sid
    pattern = str(scene.get("id_pattern") or "taibei_ue_{timestamp}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return pattern.replace("{timestamp}", stamp)


def load_pipeline_config(path: Path, *, overrides: Optional[dict] = None) -> PipelineConfig:
    path = path.resolve()
    data = _resolve_extends(_load_yaml(path), path.parent)
    if overrides:
        data = _deep_merge(data, overrides)

    scene = data.get("scene") or {}
    output = data.get("output") or {}
    pipeline = data.get("pipeline") or []
    steps: list[StepConfig] = []
    for item in pipeline:
        if not isinstance(item, dict) or "step" not in item:
            continue
        steps.append(
            StepConfig(
                step=str(item["step"]),
                enabled=bool(item.get("enabled", True)),
                depends_on=list(item.get("depends_on") or []),
                config=dict(item.get("config") or {}),
                config_ref=item.get("config_ref"),
            )
        )

    out_dir = Path(str(output.get("dir") or "output")).expanduser()
    project_root = _find_project_root(path.parent)
    if not out_dir.is_absolute():
        out_dir = (project_root / out_dir).resolve()

    return PipelineConfig(
        schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        scene_id=_ensure_scene_id(scene),
        scene_title=str(scene.get("title") or ""),
        scene_id_pattern=str(scene.get("id_pattern") or "taibei_ue_{timestamp}"),
        frame=dict(data.get("frame") or {}),
        inputs=dict(data.get("inputs") or {}),
        output_dir=out_dir,
        output_layout=str(output.get("layout") or "cityusd_v1"),
        steps=steps,
        runtime=dict(data.get("runtime") or {}),
        raw=data,
        source_path=path,
        project_root=project_root,
    )


def load_step_config_ref(cfg: PipelineConfig, step: StepConfig, package_dir: Path) -> dict:
    merged = dict(step.config)
    if step.config_ref:
        ref = Path(step.config_ref)
        if not ref.is_absolute():
            candidates = [
                cfg.project_root / ref,
                cfg.source_path.parent / ref,
            ]
            ref = next((c for c in candidates if c.is_file()), candidates[0])
        if ref.suffix.lower() == ".json":
            merged = _deep_merge(json.loads(ref.read_text(encoding="utf-8")), merged)
        else:
            merged = _deep_merge(_load_yaml(ref), merged)
    return merged


def write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
