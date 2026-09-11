# -*- coding: utf-8 -*-
# 中文说明：OctoMap 3D 配置加载/校验（供 cityusd.octomap3d 与 nav_octomap 使用）。
"""
costmap_config.py —— v2 配置模块：默认值 + YAML 加载 + 校验

可配置项（用户约定的 9 项，其余逻辑全部固定写死，见 FIXED）：
  osm / dem / out_prefix / out_dir / resolution / bbox / height.{...}
"""
import os

import yaml

DEFAULTS = {
    "osm": "",
    "dem": "",
    "out_prefix": "taibei",
    "out_dir": None,          # None=当前目录
    "resolution": 4.0,        # 体素分辨率（米）
    "origin": None,           # None=自动取数据左下角(对齐网格)；或 [UTM_x, UTM_y, 绝对海拔z]
    "bbox": None,             # None=全城；[lonmin, latmin, lonmax, latmax]
    "height": {
        "floor_height_m": 3.0,      # 一层楼高：building:levels × 该值
        "default_height_m": 10.0,   # 无高度信息默认楼高
        "min_height_m": 1.0,        # 高度截断下限
        "max_height_m": 600.0,      # 高度截断上限
    },
}

# 固定逻辑（按设计写死，不开放配置）
FIXED = {
    "sample_m": None,          # None => resolution/2（足迹采样）
    "terrain_step_m": None,    # None => resolution（地形采样）
    "terrain_margin_m": 200.0, # 地形外扩
    "min_area_m2": 4.0,        # 最小建筑面积
    "exclude_building_values": ("no", "none", "false", "0"),
    "ground_as_free": False,
    "include_terrain": True,
    "save_points": False,
    "save_voxels": False,
    "visualize": False,
}


def load_config(path=None, overrides=None):
    """加载 YAML 配置（未填项补默认值），可选叠加 overrides，然后校验。

    路径解析规则：相对路径按"配置文件所在目录"解析（傻瓜式，从哪运行都行）；
    不传 path（纯编程调用）时按当前工作目录解析。

    用法:
      cfg = load_config("config.yaml")
      cfg = load_config(None, {"osm": "x.pbf", "dem": "y.tif", "resolution": 2})
    """
    cfg = dict(DEFAULTS)
    cfg["height"] = dict(DEFAULTS["height"])
    base = None
    if path:
        path = os.path.abspath(path)
        base = os.path.dirname(path)
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        _deep_update(cfg, user)
    if overrides:
        _deep_update(cfg, overrides)
    _resolve_paths(cfg, base)
    validate(cfg)
    return cfg


def _resolve_paths(cfg, base):
    """把相对路径按 base（配置文件目录）解析成绝对路径；base=None 时不动"""
    if base is None:
        return
    for key in ("osm", "dem"):
        v = cfg.get(key)
        if v and not os.path.isabs(v):
            cfg[key] = os.path.join(base, v)
    od = cfg.get("out_dir")
    if od and not os.path.isabs(od):
        cfg["out_dir"] = os.path.join(base, od)


def _deep_update(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def validate(cfg):
    """配置合法性校验，错误抛 ValueError"""
    errs = []
    if not cfg.get("osm"):
        errs.append("osm 未指定")
    elif not os.path.isfile(cfg["osm"]):
        errs.append("osm 文件不存在: %r" % cfg["osm"])
    if not cfg.get("dem"):
        errs.append("dem 未指定")
    elif not os.path.isfile(cfg["dem"]):
        errs.append("dem 文件不存在: %r" % cfg["dem"])
    if not (isinstance(cfg.get("resolution"), (int, float)) and cfg["resolution"] > 0):
        errs.append("resolution 必须为正数: %r" % cfg.get("resolution"))
    bbox = cfg.get("bbox")
    if bbox is not None:
        ok = (isinstance(bbox, (list, tuple)) and len(bbox) == 4 and
              all(isinstance(v, (int, float)) for v in bbox) and
              bbox[0] < bbox[2] and bbox[1] < bbox[3])
        if not ok:
            errs.append("bbox 需为 [lonmin, latmin, lonmax, latmax] 且 min<max: %r" % (bbox,))
    origin = cfg.get("origin")
    if origin is not None:
        ok = (isinstance(origin, (list, tuple)) and len(origin) == 3 and
              all(isinstance(v, (int, float)) for v in origin))
        if not ok:
            errs.append("origin 需为 [UTM_x, UTM_y, 绝对海拔z] 或 null(自动): %r" % (origin,))
    h = cfg.get("height") or {}
    for k in ("floor_height_m", "default_height_m", "min_height_m", "max_height_m"):
        v = h.get(k)
        if not (isinstance(v, (int, float)) and v > 0):
            errs.append("height.%s 必须为正数: %r" % (k, v))
    if (isinstance(h.get("max_height_m"), (int, float)) and
            isinstance(h.get("min_height_m"), (int, float)) and
            h["max_height_m"] <= h["min_height_m"]):
        errs.append("height.max_height_m 必须大于 height.min_height_m")
    if errs:
        raise ValueError("配置校验失败:\n  - " + "\n  - ".join(errs))


def dump(cfg):
    """把配置转成可读文本（调试用）"""
    import json
    return json.dumps(cfg, ensure_ascii=False, indent=2)
