# -*- coding: utf-8 -*-
# 中文说明：独立调试入口（读旁路 config.yaml）；正式流程请用 build_scene_pipeline nav_octomap。
"""Standalone OctoMap 3D entry (optional). Prefer Scene Package pipeline step nav_octomap."""
from __future__ import annotations

import os
import sys
import traceback


def _find_config():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "config.yaml"),
        os.path.join(os.path.dirname(here), "config.yaml"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def main():
    cfg_path = _find_config()
    if cfg_path is None:
        print("找不到 config.yaml：请放到本目录或上一级，或使用 build_scene_pipeline --only nav_octomap")
        return 1
    try:
        from cityusd.octomap3d.costmap_config_3d import load_config
        from cityusd.octomap3d.pipeline_3d import build_costmap

        cfg = load_config(cfg_path)
        print("配置来源: %s" % cfg_path)
        print(
            "分辨率 %.1f m | bbox=%s | 输出 -> %s/%s.bt"
            % (cfg["resolution"], cfg["bbox"], cfg["out_dir"], cfg["out_prefix"])
        )

        result = build_costmap(cfg)
        m = result["meta"]
        print("\n全部完成")
        print("  .bt       : %s" % result["outputs"]["bt"])
        print("  meta.json : %s" % result["outputs"]["meta_json"])
        print(
            "  占用体素   : %d | origin=%s | 用时 %.1fs"
            % (m["occupied_voxels_total"], m["origin"], m["elapsed_s"])
        )
        return 0
    except Exception as e:
        print("\n运行出错：%s" % e)
        if os.environ.get("V2_DEBUG"):
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
