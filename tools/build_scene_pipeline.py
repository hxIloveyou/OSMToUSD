#!/usr/bin/env python3
"""Scene Package pipeline CLI (schema v0.3).

Examples:
  python tools/build_scene_pipeline.py --scene taibei_ue
  python tools/build_scene_pipeline.py --scene taibei_debug --only resolve_extent,osm_city_usd
  python tools/build_scene_pipeline.py --config SceneData/taibei_ue/input/config/pipeline.yaml
  python tools/build_scene_pipeline.py --scene taibei_ue --resume
"""
# 中文说明：
# 用途：按场景配置编排并执行完整构建（extent → terrain → OSM USD → … → zip）。
# 用法：优先 --scene <id>；也可用 --config 指向 pipeline.yaml。

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
_ROOT = _TOOLS.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from cityusd.pipeline.runner import run_pipeline  # noqa: E402
from cityusd.pipeline.schema import (  # noqa: E402
    load_pipeline_config,
    load_scene_pipeline,
    scene_pipeline_path,
)


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments.

    功能：解析命令行参数。
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, help="Path to pipeline.yaml")
    p.add_argument(
        "--scene",
        type=str,
        help="Load SceneData/<scene>/input/config/pipeline.yaml",
    )
    p.add_argument(
        "--preset",
        choices=("taibei_ue", "taibei_debug"),
        help="Deprecated alias for --scene",
    )
    p.add_argument("--only", type=str, default="", help="Comma-separated step names")
    p.add_argument("--resume", action="store_true", help="Skip steps with matching input_hash in manifest")
    p.add_argument(
        "--release",
        action="store_true",
        help="Dated scene id (YYYYMMDD) + backup sibling packages under output/backups/",
    )
    p.add_argument("--set", dest="overrides", action="append", default=[], help="dotted.key=value override")
    return p.parse_args(argv)


def _apply_overrides(base: dict, pairs: list[str]) -> dict:
    """Apply dotted.key=value overrides onto a nested dict.

    功能：把 --set 列表写入配置字典（就地修改并返回）。
    """
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"Invalid --set (need key=value): {item}")
        key, _, val = item.partition("=")
        cur = base
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        # Infer bool / int / float / str
        if val.lower() in ("true", "false"):
            cur[parts[-1]] = val.lower() == "true"
        else:
            try:
                cur[parts[-1]] = int(val)
            except ValueError:
                try:
                    cur[parts[-1]] = float(val)
                except ValueError:
                    cur[parts[-1]] = val
    return base


def main(argv=None) -> int:
    """Load scene config and run the pipeline.

    功能：加载场景配置并执行流水线。返回 0 成功。
    """
    args = parse_args(argv)
    overrides: dict = {}
    if args.release:
        # Release mode: date-stamped scene id + package backup flags
        overrides = _apply_overrides(
            overrides,
            [
                "scene.id=",
                "runtime.scene_id_stamp=date",
                "runtime.backup_previous_packages=true",
                "runtime.backup_self_if_exists=true",
            ],
        )
    if args.overrides:
        overrides = _apply_overrides(overrides, args.overrides)

    scene_id = args.scene or args.preset
    if args.config:
        cfg_path = args.config.resolve()
        if not cfg_path.is_file():
            print(f"ERROR: config not found: {cfg_path}", file=sys.stderr)
            return 1
        cfg = load_pipeline_config(cfg_path, overrides=overrides or None)
        cfg_path_display = cfg_path
    elif scene_id:
        cfg_path = scene_pipeline_path(_ROOT, scene_id)
        if not cfg_path.is_file():
            print(f"ERROR: scene pipeline not found: {cfg_path}", file=sys.stderr)
            return 1
        cfg = load_scene_pipeline(scene_id, project_root=_ROOT, overrides=overrides or None)
        cfg_path_display = cfg_path
    else:
        # Default scene when neither --config nor --scene is given
        cfg_path = scene_pipeline_path(_ROOT, "taibei_ue")
        if not cfg_path.is_file():
            print(f"ERROR: default scene pipeline not found: {cfg_path}", file=sys.stderr)
            return 1
        cfg = load_scene_pipeline("taibei_ue", project_root=_ROOT, overrides=overrides or None)
        cfg_path_display = cfg_path

    only = [s.strip() for s in args.only.split(",") if s.strip()] or None

    print(f"Pipeline config : {cfg_path_display}")
    print(f"Scene id        : {cfg.scene_id}")
    print(f"Output package  : {cfg.package_dir()}")
    print(f"Enabled steps   : {[s.step for s in cfg.enabled_steps()]}")

    try:
        run_pipeline(cfg, only=only, resume=bool(args.resume))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
