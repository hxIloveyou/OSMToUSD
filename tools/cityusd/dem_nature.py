"""DEM → Nature BMP + slope PGM for nav2/nature (schema v0.3)."""
# 中文说明：DEM → nature BMP 与坡度 PGM。

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image

from cityusd.bmp_slope_occupancy import build_slope_occupancy
from cityusd.nav2_paths import NAV2_DEM, NAV2_NATURE
from cityusd.types import ExtentM, Origin

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def elevation_to_bmp(elev: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Encode elevation as MAVS BMP: gray=128 is map center, h = scale*(gray-128)."""
    data = elev.astype(np.float32, copy=False)
    mask = ~np.isfinite(data)
    valid = data[~mask]
    if valid.size == 0:
        raise ValueError("No valid elevation pixels in DEM")

    h, w = data.shape
    elev_center = float(data[h // 2, w // 2])
    if not np.isfinite(elev_center):
        elev_center = float(np.median(valid))
    elev_min = float(np.min(valid))
    elev_max = float(np.max(valid))
    half_span = max(elev_center - elev_min, elev_max - elev_center, 50.0)

    elev_rel = data - elev_center
    gray = np.clip(128.0 + elev_rel / half_span * 127.0, 0.0, 255.0).astype(np.uint8)
    gray[mask] = 0
    scale = half_span / 127.0
    return gray, elev_center, scale


def _write_pgm(path: Path, occ: np.ndarray) -> None:
    h, w = occ.shape
    header = f"P5\n{w} {h}\n255\n".encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + np.ascontiguousarray(occ, dtype=np.uint8).tobytes())


def _write_nature_bmp_yaml(
    path: Path,
    *,
    resolution: float,
    scale: float,
    max_slope: float,
    cliff_slope: float,
    origin_x: float,
    origin_y: float,
    bmp_rel: str,
    pgm_rel: str,
) -> None:
    payload = {
        "nature_bmp": {
            "resolution": float(resolution),
            "scale": float(scale),
            "max_slope": float(max_slope),
            "cliff_slope": float(cliff_slope),
            "origin_x": float(origin_x),
            "origin_y": float(origin_y),
            "frame_id": "map",
            "align_mavs": False,
            "bmp_path": bmp_rel.replace("\\", "/"),
            "bmp_paths": [bmp_rel.replace("\\", "/")],
            "pgm_fallback_path": pgm_rel.replace("\\", "/"),
            "pgm_fallback_paths": [pgm_rel.replace("\\", "/")],
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is not None:
        path.write_text(
            "# Nature BMP aligned to scene map_local (SW origin from extent.json).\n"
            + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_nav2_nature_from_dem_utm(
    dem_utm_path: Path,
    package_dir: Path,
    *,
    extent: ExtentM,
    origin: Origin,
    name: str,
    max_slope: float = 0.35,
    cliff_slope: float = 0.70,
    nature_dir_rel: str = NAV2_NATURE,
    dem_dir_rel: str = NAV2_DEM,
) -> dict[str, Any]:
    """功能：DEM UTM → nature 产物。"""
    if not dem_utm_path.is_file():
        raise FileNotFoundError(f"DEM GeoTIFF not found: {dem_utm_path}")

    nature_dir = package_dir / nature_dir_rel
    dem_dir = package_dir / dem_dir_rel
    nature_dir.mkdir(parents=True, exist_ok=True)
    dem_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_utm_path) as ds:
        elev = ds.read(1).astype(np.float32)
        if ds.nodata is not None:
            elev = np.where(elev == ds.nodata, np.nan, elev)
        res_x = abs(float(ds.transform.a))
        res_y = abs(float(ds.transform.e))
        resolution = float((res_x + res_y) / 2.0)

    gray, elev_center, scale = elevation_to_bmp(elev)
    occ = build_slope_occupancy(gray, resolution, scale, max_slope)

    bmp_name = f"{name}.bmp"
    pgm_name = f"{name}.pgm"
    bmp_path = nature_dir / bmp_name
    pgm_path = nature_dir / pgm_name
    yaml_path = nature_dir / "nature_bmp.yaml"

    Image.fromarray(gray, mode="L").save(bmp_path, format="BMP")
    _write_pgm(pgm_path, occ)

    bmp_rel = f"./{nature_dir_rel}/{bmp_name}"
    pgm_rel = f"./{nature_dir_rel}/{pgm_name}"
    _write_nature_bmp_yaml(
        yaml_path,
        resolution=resolution,
        scale=scale,
        max_slope=max_slope,
        cliff_slope=cliff_slope,
        origin_x=float(extent.west),
        origin_y=float(extent.south),
        bmp_rel=bmp_rel,
        pgm_rel=pgm_rel,
    )

    dem_meta = {
        "source": str(dem_utm_path.relative_to(package_dir).as_posix())
        if dem_utm_path.is_relative_to(package_dir)
        else str(dem_utm_path),
        "resolution_m": resolution,
        "size_px": [int(elev.shape[1]), int(elev.shape[0])],
        "elev_center_m": elev_center,
        "bmp_scale_m_per_gray": scale,
        "utm_epsg": origin.epsg,
        "map_local_origin": [float(extent.west), float(extent.south), 0.0],
    }
    dem_meta_path = dem_dir / f"{name}_meta.json"
    dem_meta_path.write_text(json.dumps(dem_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    readme = nature_dir / "README.txt"
    readme.write_text(
        "Nature / off-road assets from terrain DEM (nav2_nature step).\n"
        f"BMP + slope PGM from {dem_utm_path.name}; origin aligned to map_local SW.\n",
        encoding="utf-8",
    )

    free = int(np.sum(occ == 254))
    occupied = int(np.sum(occ == 0))
    return {
        "dem_source": str(dem_utm_path),
        "name": name,
        "resolution_m": resolution,
        "scale": scale,
        "elev_center_m": elev_center,
        "max_slope": max_slope,
        "free_px": free,
        "occupied_px": occupied,
        "outputs": [
            str((nature_dir / bmp_name).relative_to(package_dir).as_posix()),
            str((nature_dir / pgm_name).relative_to(package_dir).as_posix()),
            str(yaml_path.relative_to(package_dir).as_posix()),
            str(dem_meta_path.relative_to(package_dir).as_posix()),
        ],
    }
