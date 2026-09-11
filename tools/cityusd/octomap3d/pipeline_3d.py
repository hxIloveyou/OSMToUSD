# -*- coding: utf-8 -*-
"""
pipeline_3d.py —— v2 建图流水线（自包含实现，仅依赖第三方库）

包含：UTM 投影 / DEM 双线性采样 / 建筑几何 / 足迹采样 / 平屋顶体素 /
流式插入 OctoMap / meta 输出。对外暴露：
  build_costmap(cfg) -> dict
固定逻辑（见 costmap_config_3d.FIXED）：sample=res/2、terrain_step=res、
margin=200m、最小面积 4m²、高度链固定、地形为 occupied、只输出 .bt + _meta.json。

【内存优化说明】(2024 低内存改造)
  旧实现会把“全城所有建筑的原始体素点”以 float64 三维数组全部累积在内存里
  （1m 分辨率可达 ~16 亿点 ≈ 40GB+，再加 vstack / 去重 / 地形 meshgrid 的
  多份拷贝，60GB 也会爆）。本版本改为：
    1. origin 在建点前就确定（配置 origin 或由 DEM 范围推算），不再依赖全量
       点云的最小值；
    2. 建筑体素按“单建筑/单部件”生成 → 局部 np.unique 去重 → 攒批
       (默认 ~2M 点) 直接 tree.updateNodes 插入 → 立即释放；
    3. 地形网格按行分块生成（每块 ~100 万点），块内采样、块内插入、块内释放；
    4. 全程不再存在任何全量点云数组；唯一随规模增长的内存是 octomap 树本身
       （这是写 .bt 的必然下限），外加 OSM 解析与 DEM 的固定开销。
"""
import gc
import json
import math
import os
import re
import time

# 仅清掉明显错误的 PROJ 路径（如 PostgreSQL 自带），避免干扰 CityUsd 其它步骤的 GDAL。
for _k in ("PROJ_LIB", "PROJ_DATA"):
    _v = os.environ.get(_k) or ""
    if "PostgreSQL" in _v or "postgresql" in _v.lower():
        os.environ.pop(_k, None)

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.warp import transform_bounds
from shapely import contains_xy, make_valid
from shapely.geometry import Polygon
from shapely.ops import transform as sh_transform, unary_union

from cityusd.octomap3d.osm_count_3d import count_buildings
from cityusd.octomap3d.osm_extract_3d import extract_buildings


def _require_octomap():
    """功能：延迟导入 octomap，缺依赖时给出安装提示。"""
    try:
        import octomap
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "nav_octomap requires the 'octomap' package (pip install octomap-python). "
            f"Original error: {exc}"
        ) from exc
    return octomap

# ================================================================ 通用工具
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

# octree 可表达范围 = ±2^15 * res；键打包时给每轴加该常数平移，保证全城
# 用同一套(ix,iy,iz)->int64 键且不碰撞（无需像旧版那样依赖“每批最小值平移”）。
_KEY_SHIFT = 1 << 15

# 建筑体素攒批上限（点）；批内为 float64 3 列，2M 点约 48MB 瞬时。
_FLUSH_PTS = 2_000_000

# 地形分块：每块约这么多网格点（含中间变换数组后瞬时峰值 ~100-200MB）
_TERRAIN_CHUNK_PTS = 1_000_000


def _peak_rss_mb():
    """Linux 峰值 RSS（KB）；Windows 无 resource 模块则返回 None（仅提示用）"""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return None


def _log_rss(tag):
    mb = _peak_rss_mb()
    if mb:
        print("    [mem] %s 后峰值RSS ≈ %.0f MB" % (tag, mb))


def _first_number(s):
    """从字符串中提取第一个数字；失败返回 None"""
    if s is None:
        return None
    m = _NUM_RE.search(str(s))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def utm_crs_for(lon, lat):
    zone = int((lon + 180.0) // 6.0) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg), zone


def height_chain(tags, stats, hcfg):
    """高度链（配置驱动）：height > levels×floor_height_m > default；越界截断"""
    h = _first_number(tags.get("height"))
    src = "height"
    if h is None or h <= 0:
        lv = _first_number(tags.get("building:levels"))
        if lv is not None and lv > 0:
            h = lv * hcfg["floor_height_m"]
            src = "levels"
        else:
            h = hcfg["default_height_m"]
            src = "default"
    if h < hcfg["min_height_m"]:
        h = hcfg["min_height_m"]
        src += "+clamp"
    if h > hcfg["max_height_m"]:
        h = hcfg["max_height_m"]
        src += "+clamp"
    key = "hsrc_" + src.split("+")[0]
    stats[key] = stats.get(key, 0) + 1
    return h, src


# ================================================================ DEM 采样
def sample_dem(dem, arr, x_crs, y_crs):
    """在 DEM 的 CRS 坐标处双线性采样高程；越界/无效 -> nan。
    注意：rasterio 逆仿射 ~transform*(x,y) 返回 (列, 行)，别搞反。"""
    inv = ~dem.transform
    cols, rows = inv * (x_crs, y_crs)
    H, W = arr.shape
    r0 = np.floor(rows).astype(np.int64)
    c0 = np.floor(cols).astype(np.int64)
    dr = rows - r0
    dc = cols - c0
    ok = (r0 >= 0) & (r0 + 1 < H) & (c0 >= 0) & (c0 + 1 < W)
    rr = np.clip(r0, 0, H - 2)
    cc = np.clip(c0, 0, W - 2)
    z = (arr[rr, cc] * (1 - dr) * (1 - dc) +
         arr[rr, cc + 1] * (1 - dr) * dc +
         arr[rr + 1, cc] * dr * (1 - dc) +
         arr[rr + 1, cc + 1] * dr * dc)
    z[~ok] = np.nan
    return z


# ================================================================ 几何与足迹
def make_polygon_utm(b, t_4326_utm):
    """把建筑物（way 或 relation）构造成 UTM 多边形；失败返回 None"""
    try:
        if b["source"] == "way":
            poly = make_valid(Polygon(b["ring"]))
        else:
            outers = unary_union([make_valid(Polygon(r)) for r in b["outer"]])
            if outers.geom_type == "Polygon":
                base = [outers]
            elif outers.geom_type == "MultiPolygon":
                base = list(outers.geoms)
            else:
                return None
            if b["inner"]:
                holes = unary_union([make_valid(Polygon(r)) for r in b["inner"]])
                tmp = []
                for p in base:
                    try:
                        d = p.difference(holes)
                    except Exception:
                        continue
                    if d.is_empty:
                        continue
                    if d.geom_type == "Polygon":
                        tmp.append(d)
                    elif d.geom_type == "MultiPolygon":
                        tmp.extend(d.geoms)
                base = tmp
            if not base:
                return None
            poly = unary_union(base)
        poly = make_valid(poly)
        if poly.geom_type == "GeometryCollection":
            parts = [g for g in poly.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
            poly = unary_union(parts) if parts else None
        if poly is None or poly.is_empty:
            return None
        return sh_transform(t_4326_utm.transform, poly)
    except Exception:
        return None


def sample_footprint(poly_utm, spacing):
    """足迹采样：边界 + 内部网格，间距 spacing 米"""
    pts = []

    def ring_pts(ring):
        out = []
        L = ring.length
        n = max(2, int(math.ceil(L / spacing)))
        for i in range(n):
            p = ring.interpolate(L * i / n)
            out.append((p.x, p.y))
        return out

    for ring in [poly_utm.exterior] + list(poly_utm.interiors):
        pts.extend(ring_pts(ring))

    minx, miny, maxx, maxy = poly_utm.bounds
    xs = np.arange(minx + spacing / 2, maxx, spacing)
    ys = np.arange(miny + spacing / 2, maxy, spacing)
    if len(xs) and len(ys):
        gx, gy = np.meshgrid(xs, ys)
        gx = gx.ravel()
        gy = gy.ravel()
        inside = contains_xy(poly_utm, gx, gy)
        pts.extend(zip(gx[inside].tolist(), gy[inside].tolist()))
    return pts


def building_volume_points(pts_utm, z0, h, res):
    """水平屋顶体素：屋顶 = min(有效 z0)+h，每列从自己的 z0 摞到屋顶。
    返回该建筑（部件）的原始体素点列（含因足迹采样间距 < res 产生的重复点，
    由调用方按体素键去重）。"""
    valid = np.isfinite(z0)
    k = int(valid.sum())
    if k == 0:
        return np.zeros((0, 3))
    pts = pts_utm[valid]
    zz = z0[valid]
    roof = float(np.min(zz)) + h
    nz_i = np.ceil((roof - zz) / res).astype(np.int64)
    nz_i = np.maximum(nz_i, 1)
    max_nz = int(nz_i.max())
    col = np.arange(max_nz, dtype=np.float64)[None, :]
    zs = zz[:, None] + res * col
    mask = col < nz_i[:, None]
    xs = np.broadcast_to(pts[:, 0:1], zs.shape)[mask]
    ys = np.broadcast_to(pts[:, 1:2], zs.shape)[mask]
    zsel = zs[mask]
    return np.column_stack([xs, ys, zsel])


def voxel_keys_global(xyz, origin, res):
    """世界坐标 -> 全局唯一 int64 体素键（用固定平移打包，与批次无关）。
    要求各轴体素索引在 [-2^15, 2^15) 内（与 octree 可表达范围一致）。"""
    ix = np.floor((xyz[:, 0] - origin[0]) / res).astype(np.int64)
    iy = np.floor((xyz[:, 1] - origin[1]) / res).astype(np.int64)
    iz = np.floor((xyz[:, 2] - origin[2]) / res).astype(np.int64)
    return ((ix + _KEY_SHIFT) << 42) | ((iy + _KEY_SHIFT) << 21) | (iz + _KEY_SHIFT)


def dedupe_local(xyz, origin, res):
    """单建筑/部件内的体素去重（键全局一致，仅用于消掉同 cell 的重复列）。"""
    n = len(xyz)
    if n <= 1:
        return xyz
    key = voxel_keys_global(xyz, origin, res)
    _, idx = np.unique(key, return_index=True)
    return xyz[idx]


def _insert_batch(tree, rel_pts, lim, label=""):
    """把（已平移 origin 的）体素中心坐标批量插入 octomap；越界立即报错"""
    if len(rel_pts) == 0:
        return
    if np.abs(rel_pts).max() >= lim:
        raise RuntimeError(
            "体素超出 octree 可表达范围 ±%d m（%s），请检查/调整 config 的 origin"
            % (lim, label))
    tree.updateNodes(np.ascontiguousarray(rel_pts, dtype=np.float64), True)


def _b_in_bbox(b, bbox):
    """建筑物质心是否落在 bbox [lonmin,latmin,lonmax,latmax] 内"""
    if b["source"] == "way":
        ring = b["ring"]
    else:
        ring = b["outer"][0] if b["outer"] else []
    if not ring:
        return False
    lon = sum(p[0] for p in ring) / len(ring)
    lat = sum(p[1] for p in ring) / len(ring)
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


# ================================================================ 主流程
def build_costmap(cfg):
    """配置驱动建图。返回 {"ok", "meta", "outputs": {bt, meta_json}, "count"}"""
    octomap = _require_octomap()
    t0 = time.time()
    hcfg = cfg["height"]
    res = float(cfg["resolution"])
    bbox = cfg.get("bbox")
    out_dir = cfg.get("out_dir") or "."
    os.makedirs(out_dir, exist_ok=True)
    out_base = os.path.join(out_dir, cfg["out_prefix"])
    lim = 2 ** 15 * res   # octree 单向可表达范围（米）

    stats = {"params": {
        "osm": os.path.basename(cfg["osm"]), "dem": os.path.basename(cfg["dem"]),
        "out_prefix": cfg["out_prefix"], "out_dir": out_dir,
        "resolution": res, "bbox": bbox, "height": dict(hcfg)}}

    # ---- [0] 统计 ----
    cnt = count_buildings(cfg["osm"])
    stats["count"] = cnt
    print("==> [0/5] 统计建筑: way=%d relation=%d 独立=%d"
          % (cnt["way_count"], cnt["relation_count"], cnt["dedup_total"]))

    # ---- [1] 解析 ----
    print("==> [1/5] 解析 OSM 建筑物 ...")
    t = time.time()
    buildings, pstats = extract_buildings(cfg["osm"])
    stats.update(pstats)
    print("    %d 个建筑物，用时 %.1fs" % (len(buildings), time.time() - t))
    _log_rss("[1/5] OSM解析")

    # ---- [2] DEM ----
    print("==> [2/5] 加载 DEM ...")
    dem = rasterio.open(cfg["dem"])
    arr = dem.read(1).astype(np.float64)
    if dem.nodata is not None:
        arr[arr == dem.nodata] = np.nan

    # ---- [3] 坐标与范围 ----
    lons, lats = [], []
    for b in buildings[:2000]:
        if b["source"] == "way":
            lons.append(b["ring"][0][0]); lats.append(b["ring"][0][1])
        elif b["outer"]:
            lons.append(b["outer"][0][0][0]); lats.append(b["outer"][0][0][1])
    if not lons:
        lons = [dem.bounds.left]; lats = [dem.bounds.top]
    mean_lon, mean_lat = float(np.mean(lons)), float(np.mean(lats))
    utm_crs, zone = utm_crs_for(mean_lon, mean_lat)
    t_4326_utm = Transformer.from_crs(CRS.from_epsg(4326), utm_crs, always_xy=True)
    t_utm_4326 = Transformer.from_crs(utm_crs, CRS.from_epsg(4326), always_xy=True)
    dem_is_4326 = dem.crs is not None and dem.crs.to_epsg() == 4326
    t_4326_dem = None if dem_is_4326 else Transformer.from_crs(
        CRS.from_epsg(4326), dem.crs, always_xy=True)
    if bbox:
        buildings = [b for b in buildings if _b_in_bbox(b, bbox)]
        print("    按 bbox 过滤后剩余 %d 个建筑物" % len(buildings))
    if not buildings:
        raise RuntimeError("没有可处理的建筑物（检查 bbox）")

    # ---- origin：建点之前先定（配置 origin，或由 DEM 范围推算），
    #      从而允许建筑/地形体素“边算边插入”，不再需要先攒全量点云求 min ----
    dem_utm_bounds = None
    try:
        dem_utm_bounds = transform_bounds(dem.crs, utm_crs, *dem.bounds,
                                          densify_pts=21)
    except Exception:
        pass
    if cfg.get("origin") is not None:
        o = np.array([float(v) for v in cfg["origin"]])
        origin = np.array([math.floor(o[0] / res) * res,
                           math.floor(o[1] / res) * res,
                           math.floor(o[2] / res) * res])
        print("    使用配置固定 origin: %s（对齐后 %s）" % (o, origin))
        # 快速失败：若连 DEM 范围都超 octree，无需再等建筑生成
        if dem_utm_bounds is not None:
            zb = float(np.nanmin(arr)) if np.isfinite(arr).any() else 0.0
            far = max(abs(dem_utm_bounds[0] - origin[0]),
                      abs(dem_utm_bounds[2] - origin[0]),
                      abs(dem_utm_bounds[1] - origin[1]),
                      abs(dem_utm_bounds[3] - origin[1]),
                      abs(zb - origin[2]) + res)
            if far >= lim:
                raise RuntimeError(
                    "固定 origin 距 DEM 太远（约 %d m > %d m），"
                    "数据无法放入 octree，请检查 origin" % (far, lim))
    else:
        if dem_utm_bounds is None:
            raise RuntimeError("无法推算 DEM 的 UTM 范围作为自动 origin")
        o = np.array([dem_utm_bounds[0], dem_utm_bounds[1], 0.0])
        origin = np.array([math.floor(o[0] / res) * res,
                           math.floor(o[1] / res) * res, 0.0])
        if np.isfinite(arr).any():
            zmin = float(np.nanmin(arr))
            origin[2] = math.floor(zmin / res) * res - res   # 留一个体素余量
        print("    自动 origin（DEM左下角对齐）: %s" % origin)
    origin = np.asarray(origin, dtype=np.float64)

    # ---- [4] 建筑体素（sample=res/2 固定；边算边插入 octomap）----
    print("==> [3/5] 生成建筑物体素点（流式插入 octomap） ...")
    sample = res / 2.0
    tree = octomap.OcTree(res)
    pending = []                       # 待插入的“已平移体素中心”数组列表
    n_pending = 0
    n_processed = n_skip_geom = n_skip_area = n_no_dem = n_too_small = n_foot = 0
    bld_raw_pts = 0                    # 去重前的原始体素点数（统计用）
    bld_unique = 0                     # 局部去重后、实际插入点数（跨建筑重复未扣）
    # 地形范围：只统计“成功生成体素”的部件（与旧版 bld_polys_utm 口径一致）
    tminx = tminy = math.inf
    tmaxx = tmaxy = -math.inf

    def flush_buildings():
        nonlocal pending, n_pending, bld_unique
        if not pending:
            return
        batch = np.concatenate(pending, axis=0)
        pending = []
        n_pending = 0
        _insert_batch(tree, batch, lim, "building")
        bld_unique += len(batch)
        del batch

    for i, b in enumerate(buildings):
        poly_utm = make_polygon_utm(b, t_4326_utm)
        if poly_utm is None or poly_utm.is_empty:
            n_skip_geom += 1
            continue
        parts = [poly_utm] if poly_utm.geom_type == "Polygon" else list(poly_utm.geoms)
        ok_any, non_tiny = False, 0
        for part in parts:
            if part.area < 4.0:          # 最小面积（固定）
                n_skip_area += 1
                continue
            non_tiny += 1
            foot = np.array(sample_footprint(part, sample), dtype=np.float64)
            if len(foot) == 0:
                continue
            lon, lat = t_utm_4326.transform(foot[:, 0], foot[:, 1])
            if dem_is_4326:
                xc, yc = lon, lat
            else:
                xc, yc = t_4326_dem.transform(lon, lat)
            z0 = sample_dem(dem, arr, xc, yc)
            h, hsrc = height_chain(b["tags"], stats, hcfg)
            vol = building_volume_points(foot, z0, h, res)
            if len(vol) == 0:
                continue
            bld_raw_pts += len(vol)
            vol = dedupe_local(vol, origin, res)     # 消掉同 cell 重复列
            if len(vol) == 0:
                continue
            n_foot += len(foot)
            pending.append(np.ascontiguousarray(vol - origin, dtype=np.float64))
            n_pending += len(vol)
            if n_pending >= _FLUSH_PTS:
                flush_buildings()
            # 更新地形范围（该部件有体素才计入，与旧版一致）
            bx = part.bounds
            if bx[0] < tminx: tminx = bx[0]
            if bx[1] < tminy: tminy = bx[1]
            if bx[2] > tmaxx: tmaxx = bx[2]
            if bx[3] > tmaxy: tmaxy = bx[3]
            ok_any = True
        n_processed += 1
        if not ok_any:
            if non_tiny == 0:
                n_too_small += 1
            else:
                n_no_dem += 1
        if (i + 1) % 5000 == 0:
            print("    已处理 %d/%d 个建筑物 ..." % (i + 1, len(buildings)))
    flush_buildings()
    del buildings                            # 尽早释放 OSM 几何
    gc.collect()
    stats.update({"buildings_processed": n_processed, "skip_geom": n_skip_geom,
                  "skip_small_area": n_skip_area, "buildings_no_dem": n_no_dem,
                  "buildings_too_small": n_too_small,
                  "footprint_points": n_foot, "building_points_raw": bld_raw_pts,
                  "building_voxels_local_unique": bld_unique})
    print("    处理 %d 个建筑物，足迹点 %d，原始体素点 %d（局部去重后插入 %d）"
          % (n_processed, n_foot, bld_raw_pts, bld_unique))
    _log_rss("[3/5] 建筑体素")

    # ---- [5] 地形点云（margin=200 固定，step=res；按行分块流式插入）----
    print("==> [4/5] 生成地形点云（分块流式插入） ...")
    gnd_pts_total = 0
    have_terrain = math.isfinite(tminx)
    if have_terrain:
        xmin = tminx - 200.0
        ymin = tminy - 200.0
        xmax = tmaxx + 200.0
        ymax = tmaxy + 200.0
        try:
            db = dem_utm_bounds if dem_utm_bounds is not None else \
                transform_bounds(dem.crs, utm_crs, *dem.bounds, densify_pts=21)
            xmin = max(xmin, db[0]); xmax = min(xmax, db[2])
            ymin = max(ymin, db[1]); ymax = min(ymax, db[3])
        except Exception:
            pass
        xs = np.arange(xmin, xmax, res)          # 与旧版一致：网格角点采样
        ys = np.arange(ymin, ymax, res)
        nx, ny = len(xs), len(ys)
        print("    地形网格 %d x %d = %d 点（分块插入）"
              % (nx, ny, nx * ny))
        rows_per = max(1, min(ny, int(_TERRAIN_CHUNK_PTS // max(nx, 1))))
        for r0 in range(0, ny, rows_per):
            r1 = min(ny, r0 + rows_per)
            yc = ys[r0:r1]
            gx2, gy2 = np.meshgrid(xs, yc)
            ggx = gx2.ravel()
            ggy = gy2.ravel()
            lon, lat = t_utm_4326.transform(ggx, ggy)
            if dem_is_4326:
                xc, yc2 = lon, lat
            else:
                xc, yc2 = t_4326_dem.transform(lon, lat)
            zg = sample_dem(dem, arr, xc, yc2)
            ok = np.isfinite(zg)
            n_ok = int(ok.sum())
            if n_ok:
                rel = np.column_stack([ggx[ok] - origin[0],
                                       ggy[ok] - origin[1],
                                       zg[ok] - origin[2]])
                _insert_batch(tree, rel, lim, "ground")
                gnd_pts_total += n_ok
                del rel
            del gx2, gy2, ggx, ggy, lon, lat, zg, ok
        # 释放每行分块产生的 Python/numpy 引用
        del xs, ys
    stats["terrain_points"] = gnd_pts_total
    print("    地形点 %d 个" % gnd_pts_total)
    dem.close()
    gc.collect()
    _log_rss("[4/5] 地形")

    # ---- 写出 ----
    if gnd_pts_total + bld_unique == 0:
        raise RuntimeError("没有任何有效点（检查 DEM 范围与 bbox）")
    print("==> [5/5] 写出 .bt ...")
    bt_path = out_base + ".bt"
    t = time.time()
    tree.writeBinary(bt_path)
    print("    写出 .bt 用时 %.1fs" % (time.time() - t))

    # 统计：占用体素总数以 octomap 树内叶子数（跨建筑/地形重复已被树去重）为准
    try:
        octree_leaves = int(tree.getNumLeafNodes())
    except Exception:
        octree_leaves = None
    stats["origin"] = [float(v) for v in origin]
    stats["building_voxels"] = bld_unique
    stats["ground_voxels"] = gnd_pts_total
    # 占用体素总数取 octomap 树内存储叶子数（实心块已被剪枝，与 .bt 大小成正比）
    stats["occupied_voxels_total"] = octree_leaves if octree_leaves else \
        bld_unique + gnd_pts_total
    # 未剪枝的占用格上限估算（建筑局部去重+地面；跨建筑/地面重叠未扣）
    stats["unique_cells_approx"] = bld_unique + gnd_pts_total
    stats["utm_zone"] = zone
    stats["elapsed_s"] = round(time.time() - t0, 1)
    meta_path = out_base + "_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print("\n完成！总用时 %.1f s" % (time.time() - t0))
    print("占用体素: 树内存储叶子 %d（.bt 实际存储量；剪枝后）；"
          "占用格估算 %d（建筑局部去重 %d + 地面 %d）"
          % (stats["occupied_voxels_total"], stats["unique_cells_approx"],
             bld_unique, gnd_pts_total))
    print("输出: %s / %s" % (bt_path, meta_path))
    _log_rss("[5/5] 完成")
    return {"ok": True, "meta": stats,
            "outputs": {"bt": bt_path, "meta_json": meta_path},
            "count": cnt}
