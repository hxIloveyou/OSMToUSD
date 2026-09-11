#!/usr/bin/env python3
"""Run nav2_nature step on an existing Scene Package (manual / resume).

Requires terrain/dem_utm.tif from a prior terrain step.

Usage:
  python tools/run_nav2_nature.py --package <USD package dir>
"""
# 中文说明：
# 用途：在已有包上单独补跑/重跑 nature（坡度/悬崖）层。

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from cityusd.pipeline.nav2_nature import run_nav2_nature  # noqa: E402
from cityusd.pipeline.schema import PipelineConfig, StepConfig  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Build a minimal PipelineConfig and call run_nav2_nature.

    功能：构造最小配置并调用 nav2_nature 步骤。
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, required=True, help="Existing Scene Package dir")
    p.add_argument(
        "--config",
        type=Path,
        default=_TOOLS.parent / "configs" / "default" / "nav2_nature.json",
        help="nav2_nature step JSON (default: configs/default/nav2_nature.json)",
    )
    args = p.parse_args(argv)

    package_dir = args.package.resolve()
    root = _TOOLS.parent
    step_cfg = json.loads(args.config.read_text(encoding="utf-8"))

    # Manual re-run: only nav2_nature; scene_id from package folder name
    cfg = PipelineConfig(
        schema_version="0.3",
        scene_id=package_dir.name,
        scene_title=package_dir.name,
        scene_id_pattern="{timestamp}",
        frame={},
        inputs={"dem": {"path": "", "optional": True}},
        output_dir=package_dir.parent,
        output_layout="cityusd_v1",
        steps=[StepConfig(step="nav2_nature", enabled=True, config=step_cfg)],
        runtime={},
        raw={},
        source_path=args.config,
        project_root=root,
    )

    written = run_nav2_nature(cfg, package_dir, print)
    print("run_nav2_nature OK")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
