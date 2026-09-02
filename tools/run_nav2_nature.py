#!/usr/bin/env python3
"""Run nav2_nature step on an existing Scene Package (manual / resume).

Requires terrain/dem_utm.tif from a prior terrain step.

Usage:
  python tools/run_nav2_nature.py --package output/ScenePackages/taibei_ue_20260831
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from cityusd.pipeline.nav2_nature import run_nav2_nature  # noqa: E402
from cityusd.pipeline.schema import PipelineConfig, StepConfig, load_step_config_ref  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, required=True)
    p.add_argument(
        "--config",
        type=Path,
        default=_TOOLS.parent / "configs" / "nav2_nature_default.json",
    )
    args = p.parse_args(argv)

    package_dir = args.package.resolve()
    root = _TOOLS.parent
    step_cfg = __import__("json").loads(args.config.read_text(encoding="utf-8"))

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
