# 中文说明：坐标：WGS84 ↔ 局部米制 / UTM 变换。
from __future__ import annotations

from functools import lru_cache
from typing import Tuple

from pyproj import Transformer

from cityusd.types import ExtentM, Origin


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180.0) / 6.0) + 1
    return (32700 if lat < 0 else 32600) + zone


@lru_cache(maxsize=64)
def _transformer(src_crs: str, dst_crs: str) -> Transformer:
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def lonlat_to_utm(lon: float, lat: float, epsg: int) -> Tuple[float, float]:
    east, north = _transformer("EPSG:4326", f"EPSG:{epsg}").transform(lon, lat)
    return float(east), float(north)


def utm_to_lonlat(east: float, north: float, epsg: int) -> Tuple[float, float]:
    lon, lat = _transformer(f"EPSG:{epsg}", "EPSG:4326").transform(east, north)
    return float(lon), float(lat)


def _wgs84_to_utm(lon: float, lat: float, epsg: int) -> Tuple[float, float]:
    return lonlat_to_utm(lon, lat, epsg)


def _utm_to_wgs84(east: float, north: float, epsg: int) -> Tuple[float, float]:
    return utm_to_lonlat(east, north, epsg)


@lru_cache(maxsize=64)
def origin_utm(lon: float, lat: float, epsg: int) -> Tuple[float, float]:
    return lonlat_to_utm(lon, lat, epsg)


def make_origin(lon: float, lat: float, height_m: float = 0.0) -> Origin:
    """功能：由经纬度创建局部坐标原点。"""
    epsg = utm_epsg(lon, lat)
    return Origin(lon=lon, lat=lat, height_m=height_m, epsg=epsg)


def lonlat_to_local(lon: float, lat: float, origin: Origin) -> Tuple[float, float]:
    """功能：WGS84 → 局部米制坐标。"""
    east, north = lonlat_to_utm(lon, lat, origin.epsg)
    origin_east, origin_north = origin_utm(origin.lon, origin.lat, origin.epsg)
    return east - origin_east, north - origin_north


def local_to_lonlat(x_m: float, y_m: float, origin: Origin) -> Tuple[float, float]:
    """功能：局部米制 → WGS84。"""
    origin_east, origin_north = origin_utm(origin.lon, origin.lat, origin.epsg)
    return utm_to_lonlat(origin_east + x_m, origin_north + y_m, origin.epsg)


def extent_from_lonlat_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    origin: Origin,
) -> ExtentM:
    corners = [
        lonlat_to_local(west, south, origin),
        lonlat_to_local(east, south, origin),
        lonlat_to_local(west, north, origin),
        lonlat_to_local(east, north, origin),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return ExtentM(west=min(xs), south=min(ys), east=max(xs), north=max(ys))
