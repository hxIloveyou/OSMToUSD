# 中文说明：流水线配置模型与加载：scene config → configs/default 合并、JSONC、extends。
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from cityusd.scene_layout import (
    SCENE_DATA_DIRNAME,
    default_configs_dir,
    scene_config_dir,
    scene_input_dir,
    tools_assets_dir,
)

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("PyYAML required: pip install pyyaml") from exc


SCHEMA_VERSION = "0.3"

# Old config filenames → configs/default/ names (tests / docs migration).
_LEGACY_CONFIG_NAMES: dict[str, str] = {
    "terrain_default.json": "terrain.json",
    "osm_taibei_ue.json": "osm_city_usd.json",
    "osm_labels_sharded.json": "osm_labels.json",
    "nav_pgm_osm_only.json": "nav_pgm.json",
    "nav_pgm_osm_only_3m.json": "nav_pgm_3m.json",
    "nav2_nature_default.json": "nav2_nature.json",
    "overlay_default.json": "overlay.json",
    "world_cityusd_v1.json": "assemble_world.json",
    "package_zip_default.json": "package_zip.json",
}


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


def _find_project_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "configs" / "default").is_dir() and (p / "SceneData").is_dir():
            return p
        if (p / "configs").is_dir() and (p / "tools" / "cityusd").is_dir():
            return p
    return start.parent


def _extends_candidates(rel: str, base_dir: Path, project_root: Path) -> list[Path]:
    rel_norm = rel.replace("\\", "/").lstrip("./")
    out: list[Path] = [(base_dir / rel).resolve()]
    if rel_norm.startswith("default/"):
        out.append((project_root / "configs" / rel_norm).resolve())
    out.append((project_root / rel_norm).resolve())
    out.append((default_configs_dir(project_root) / Path(rel_norm).name).resolve())
    # de-dupe preserving order
    seen: set[Path] = set()
    uniq: list[Path] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _resolve_extends(data: dict, base_dir: Path, project_root: Optional[Path] = None) -> dict:
    extends = data.pop("extends", None) or []
    if isinstance(extends, str):
        extends = [extends]
    root = project_root or _find_project_root(base_dir)
    merged: dict = {}
    for rel in extends:
        candidates = _extends_candidates(str(rel), base_dir, root)
        preset_path = next((c for c in candidates if c.is_file()), None)
        if preset_path is None:
            raise FileNotFoundError(f"Preset not found for extends '{rel}': tried {candidates}")
        preset = _load_yaml(preset_path)
        merged = _deep_merge(merged, _resolve_extends(preset, preset_path.parent, root))
    return _deep_merge(merged, data)


@dataclass
class StepConfig:
    step: str
    enabled: bool = True
    depends_on: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    config_ref: Optional[str] = None


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

    def scene_root(self) -> Path:
        """Scene folder: SceneData/{id} when output_dir is …/output; else output_dir itself."""
        od = Path(self.output_dir)
        if od.name == "output":
            return od.parent
        return od

    def input_dir(self) -> Path:
        """Scene-private inputs under SceneData/{id}/input (or <output>/input in tests)."""
        local = self.scene_root() / "input"
        if Path(self.output_dir).name == "output" or local.is_dir():
            return local
        return scene_input_dir(self.project_root, self.scene_id)

    def config_dir(self) -> Path:
        return self.input_dir() / "config"

    def usd_dir(self) -> Path:
        return Path(self.output_dir) / f"{self.scene_id}-USD"

    def costmap_dir(self) -> Path:
        return Path(self.output_dir) / f"{self.scene_id}-CostMap"

    def costmap_2d_dir(self) -> Path:
        return self.costmap_dir() / "2D"

    def costmap_3d_dir(self) -> Path:
        return self.costmap_dir() / "3D"

    def costmap_rel_prefix(self) -> str:
        """Path from USD package root to CostMap/2D."""
        return f"../{self.scene_id}-CostMap/2D"

    def assets_dir(self) -> Path:
        return tools_assets_dir(self.project_root)

    def package_dir(self) -> Path:
        """USD output root (legacy name kept for step callers)."""
        return self.usd_dir()

    def ensure_dirs(self) -> dict[str, Path]:
        paths = {
            "scene_root": self.scene_root(),
            "input": self.input_dir(),
            "config": self.config_dir(),
            "usd": self.usd_dir(),
            "costmap_2d": self.costmap_2d_dir(),
            "costmap_3d": self.costmap_3d_dir(),
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        keep = paths["costmap_3d"] / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
        return paths

    def step(self, name: str) -> Optional[StepConfig]:
        for s in self.steps:
            if s.step == name:
                return s
        return None

    def enabled_steps(self) -> list[StepConfig]:
        return [s for s in self.steps if s.enabled]


def _ensure_scene_id(scene: dict, runtime: Optional[dict] = None) -> str:
    sid = str(scene.get("id") or scene.get("library_id") or "").strip()
    if sid:
        return sid
    pattern = str(scene.get("id_pattern") or "taibei_ue_{timestamp}")
    rt = runtime or {}
    stamp_mode = str(scene.get("id_stamp") or rt.get("scene_id_stamp") or "datetime").lower()
    if stamp_mode == "date":
        stamp = datetime.now().strftime("%Y%m%d")
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return pattern.replace("{timestamp}", stamp)


def _normalize_config_ref(ref: str) -> str:
    name = ref.replace("\\", "/").lstrip("./")
    for prefix in ("configs/default/", "configs/"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    base = Path(name).name
    return _LEGACY_CONFIG_NAMES.get(base, base)


def resolve_config_file(
    project_root: Path,
    scene_id: str,
    ref: str,
    *,
    scene_input: Optional[Path] = None,
    source_path: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve a step/config filename: scene input/config → configs/default → legacy paths.

功能：解析步骤配置文件路径（场景 config → default → 兼容路径）。
"""
    raw = Path(ref)
    if raw.is_absolute():
        return raw if raw.is_file() else None

    bare = _normalize_config_ref(ref)
    input_cfg = (scene_input or scene_input_dir(project_root, scene_id)) / "config"
    default_dir = default_configs_dir(project_root)
    candidates = [
        input_cfg / bare,
        default_dir / bare,
        project_root / ref,
        project_root / "configs" / "default" / bare,
        project_root / "configs" / bare,
    ]
    if source_path is not None:
        candidates.append(source_path.parent / ref)
        candidates.append(source_path.parent / bare)
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def scene_pipeline_path(project_root: Path, scene_id: str) -> Path:
    """功能：返回 SceneData/{id}/input/config/pipeline.yaml 路径。"""
    return scene_config_dir(project_root, scene_id) / "pipeline.yaml"


def load_pipeline_config(path: Path, *, overrides: Optional[dict] = None) -> PipelineConfig:
    """功能：从 pipeline.yaml 加载并解析 extends/覆盖项。"""
    path = path.resolve()
    project_root = _find_project_root(path.parent)
    data = _resolve_extends(_load_yaml(path), path.parent, project_root)
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

    rt = dict(data.get("runtime") or {})
    sid = _ensure_scene_id(scene, rt)

    out_dir_raw = output.get("dir")
    if out_dir_raw:
        out_dir = Path(str(out_dir_raw)).expanduser()
        if not out_dir.is_absolute():
            out_dir = (project_root / out_dir).resolve()
    else:
        out_dir = (project_root / SCENE_DATA_DIRNAME / sid / "output").resolve()

    return PipelineConfig(
        schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        scene_id=sid,
        scene_title=str(scene.get("title") or ""),
        scene_id_pattern=str(scene.get("id_pattern") or "taibei_ue_{timestamp}"),
        frame=dict(data.get("frame") or {}),
        inputs=dict(data.get("inputs") or {}),
        output_dir=out_dir,
        output_layout=str(output.get("layout") or "cityusd_v1"),
        steps=steps,
        runtime=rt,
        raw=data,
        source_path=path,
        project_root=project_root,
    )


def load_scene_pipeline(
    scene_id: str,
    *,
    project_root: Optional[Path] = None,
    overrides: Optional[dict] = None,
) -> PipelineConfig:
    """Load SceneData/{scene_id}/input/config/pipeline.yaml.

功能：按 scene_id 加载场景私有 pipeline.yaml。
"""
    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    path = scene_pipeline_path(root, scene_id)
    if not path.is_file():
        raise FileNotFoundError(f"Scene pipeline not found: {path}")
    return load_pipeline_config(path, overrides=overrides)


def load_step_config_ref(cfg: PipelineConfig, step: StepConfig, package_dir: Path) -> dict:
    """Merge configs: default → scene input/config → step inline config.

功能：合并 default → 场景 config → step 内联配置。
"""
    del package_dir  # kept for call-site compatibility
    ref = step.config_ref or f"{step.step}.json"
    bare = _normalize_config_ref(ref)
    merged: dict[str, Any] = {}

    default_path = default_configs_dir(cfg.project_root) / bare
    scene_path = cfg.config_dir() / bare

    loaded_any = False
    if default_path.is_file():
        merged = _load_config_file(default_path)
        loaded_any = True
    if scene_path.is_file():
        merged = _deep_merge(merged, _load_config_file(scene_path))
        loaded_any = True

    if not loaded_any:
        resolved = resolve_config_file(
            cfg.project_root,
            cfg.scene_id,
            ref,
            scene_input=cfg.input_dir(),
            source_path=cfg.source_path,
        )
        if resolved is not None:
            merged = _load_config_file(resolved)
            loaded_any = True
        elif step.config_ref:
            raise FileNotFoundError(
                f"Step config not found for {step.step!r} config_ref={step.config_ref!r} "
                f"(looked under {cfg.config_dir()} and {default_configs_dir(cfg.project_root)})"
            )

    return _deep_merge(merged, dict(step.config))


def _loads_jsonc(text: str) -> Any:
    """Parse JSON allowing // line comments and /* block comments */ (outside strings)."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                i += 2
                while i < n and text[i] not in "\r\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i = min(i + 2, n)
                continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def _load_config_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = _loads_jsonc(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data


def write_manifest(path: Path, payload: dict) -> None:
    """功能：写出 JSON manifest。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
