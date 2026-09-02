#!/usr/bin/env python3
"""Scene Package pipeline CLI (schema v0.2, M0: resolve_extent + stubs).

Examples:
  python tools/build_scene_pipeline.py --preset taibei_ue
  python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml
  python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml --only resolve_extent
  python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml --resume
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
_ROOT = _TOOLS.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from cityusd.pipeline.runner import run_pipeline  # noqa: E402
from cityusd.pipeline.schema import load_pipeline_config  # noqa: E402


def _default_examples_dir() -> Path:
    return _ROOT / "examples"


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, help="Path to pipeline.yaml")
    p.add_argument(
        "--preset",
        choices=("taibei_ue", "taibei_debug"),
        help="Use examples/<preset>.pipeline.yaml",
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
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"Invalid --set (need key=value): {item}")
        key, _, val = item.partition("=")
        cur = base
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        # naive typing
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
    args = parse_args(argv)
    if args.config:
        cfg_path = args.config.resolve()
    elif args.preset:
        cfg_path = (_default_examples_dir() / f"{args.preset}.pipeline.yaml").resolve()
    else:
        cfg_path = (_default_examples_dir() / "taibei_ue.pipeline.yaml").resolve()

    if not cfg_path.is_file():
        print(f"ERROR: config not found: {cfg_path}", file=sys.stderr)
        return 1

    overrides: dict = {}
    if args.release:
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

    cfg = load_pipeline_config(cfg_path, overrides=overrides or None)
    only = [s.strip() for s in args.only.split(",") if s.strip()] or None

    print(f"Pipeline config : {cfg_path}")
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
