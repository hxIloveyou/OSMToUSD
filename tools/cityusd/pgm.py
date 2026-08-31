"""Nav2 occupancy PGM + map.yaml export."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence, Tuple

import numpy as np
from rasterio import features
from rasterio.transform import from_origin

from cityusd.crs import lonlat_to_utm
from cityusd.types import ExtentM, Origin, RasterMeta

UNKNOWN = 205
FREE = 254
OCCUPIED = 0
COST_FREE = 0
COST_LETHAL = 254
COST_UNKNOWN = 255


def _utm_xy(lon: float, lat: float, epsg: int) -> Tuple[float, float]:
    return lonlat_to_utm(lon, lat, epsg)


def _extent_json(extent: ExtentM) -> dict:
    return extent.to_json()


def _write_pgm(path: Path, grid: np.ndarray) -> None:
    """Write binary PGM P5, 8-bit. grid shape (ny, nx), row 0 = north."""
    ny, nx = grid.shape
    header = f"P5\n{nx} {ny}\n255\n".encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + np.ascontiguousarray(grid, dtype=np.uint8).tobytes())


def _write_yaml(
    path: Path,
    image_name: str,
    resolution_m: float,
    extent: ExtentM,
    meters_per_pixel: Tuple[float, float] | None = None,
) -> None:
    extra = ""
    if meters_per_pixel is not None:
        mx, my = float(meters_per_pixel[0]), float(meters_per_pixel[1])
        if abs(mx - my) > 1e-9:
            extra = f"meters_per_pixel_xy: [{mx}, {my}]\n"
    text = (
        f"image: {image_name}\n"
        f"resolution: {resolution_m}\n"
        + extra
        + f"origin: [{float(extent.west)}, {float(extent.south)}, 0.0]\n"
        f"negate: 0\n"
        f"occupied_thresh: 0.65\n"
        f"free_thresh: 0.196\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_meta_json(
    out_json: Path,
    *,
    size_px: Tuple[int, int],
    origin: Origin,
    utm_origin: Tuple[float, float],
    extent: ExtentM,
    meters_per_pixel: Tuple[float, float],
    range_source: str,
    coverage_m: dict,
    occupancy_file: str,
    cost_file: str,
) -> None:
    payload = {
        "size_px": [int(size_px[0]), int(size_px[1])],
        "zmin_m": None,
        "zmax_m": None,
        "origin_wgs84": {
            "lon": origin.lon,
            "lat": origin.lat,
            "height_m": origin.height_m,
        },
        "utm_origin": [utm_origin[0], utm_origin[1]],
        "extent_m": _extent_json(extent),
        "coverage_m": coverage_m,
        "meters_per_pixel": [meters_per_pixel[0], meters_per_pixel[1]],
        "resolution_m": float(meters_per_pixel[0]),
        "crs_epsg": origin.epsg,
        "range_source": range_source,
        "occupancy_file": occupancy_file,
        "cost_file": cost_file,
        "occupancy_values": {"occupied": OCCUPIED, "free": FREE, "unknown": UNKNOWN},
        "cost_values": {"free": COST_FREE, "lethal": COST_LETHAL, "unknown": COST_UNKNOWN},
        "pixel_0_0": "northwest",
        "ros_origin_m": [float(extent.west), float(extent.south), 0.0],
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _rasterize_shapes(
    polys: Sequence,
    out_shape: Tuple[int, int],
    transform,
) -> np.ndarray:
    if not polys:
        return np.zeros(out_shape, dtype=np.uint8)
    shapes = ((geom, 1) for geom in polys if geom is not None and not geom.is_empty)
    return features.rasterize(
        shapes,
        out_shape=out_shape,
        transform=transform,
        fill=0,
        default_value=1,
        dtype=np.uint8,
        all_touched=False,
    )


def occupancy_to_cost(grid: np.ndarray) -> np.ndarray:
    """Nav2-style cost: 0 free, 254 lethal, 255 unknown."""
    cost = np.full(grid.shape, COST_UNKNOWN, dtype=np.uint8)
    cost[grid == FREE] = COST_FREE
    cost[grid == OCCUPIED] = COST_LETHAL
    return cost


def rasterize_pgm(
    extent: ExtentM,
    occupied_polys: list,
    free_polys: list,
    resolution_m: float,
    out_pgm: Path,
    out_yaml: Path,
    out_json: Path,
    origin: Origin,
    range_source: str,
) -> RasterMeta:
    if resolution_m <= 0:
        raise ValueError("resolution_m must be positive")
    if extent.width <= 0 or extent.height <= 0:
        raise ValueError("extent width and height must be positive")

    nx = max(1, int(math.ceil(extent.width / resolution_m)))
    ny = max(1, int(math.ceil(extent.height / resolution_m)))
    # Pad/ceil so pixel size stays square; YAML resolution == actual m/px.
    north = extent.south + ny * resolution_m
    transform = from_origin(extent.west, north, resolution_m, resolution_m)

    grid = np.full((ny, nx), UNKNOWN, dtype=np.uint8)

    # Occupied first, then free: motor roads remain navigable where footprints overlap.
    occ_mask = _rasterize_shapes(occupied_polys, (ny, nx), transform)
    grid[occ_mask > 0] = OCCUPIED

    free_mask = _rasterize_shapes(free_polys, (ny, nx), transform)
    grid[free_mask > 0] = FREE

    mpp = (float(resolution_m), float(resolution_m))
    coverage_m = {
        "west": float(extent.west),
        "south": float(extent.south),
        "east": float(extent.west) + nx * float(resolution_m),
        "north": float(extent.south) + ny * float(resolution_m),
        "width": nx * float(resolution_m),
        "height": ny * float(resolution_m),
    }
    _write_pgm(out_pgm, grid)
    cost_pgm = out_pgm.with_name("cost.pgm")
    _write_pgm(cost_pgm, occupancy_to_cost(grid))
    _write_yaml(out_yaml, out_pgm.name, float(resolution_m), extent, mpp)

    utm_origin = _utm_xy(origin.lon, origin.lat, origin.epsg)
    size_px = (nx, ny)
    _write_meta_json(
        out_json,
        size_px=size_px,
        origin=origin,
        utm_origin=utm_origin,
        extent=extent,
        meters_per_pixel=mpp,
        range_source=range_source,
        coverage_m=coverage_m,
        occupancy_file=out_pgm.name,
        cost_file=cost_pgm.name,
    )
    return RasterMeta(
        size_px=size_px,
        zmin_m=None,
        zmax_m=None,
        origin=origin,
        utm_origin=utm_origin,
        extent_m=extent,
        meters_per_pixel=mpp,
        crs_epsg=origin.epsg,
        range_source=range_source,
    )
