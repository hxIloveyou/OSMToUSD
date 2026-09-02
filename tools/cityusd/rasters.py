"""DEM heightmap and ortho imagery export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import Resampling, reproject

from cityusd.crs import lonlat_to_utm
from cityusd.types import CM_PER_M, ExtentM, Origin, RasterMeta

_HEIGHTMAP_MAX_SIDE = 2049


def _utm_xy(lon: float, lat: float, epsg: int) -> Tuple[float, float]:
    return lonlat_to_utm(lon, lat, epsg)


def _odd_target_size(width_m: float, height_m: float, max_side: int) -> Tuple[int, int]:
    """Longest side = max_side; keep aspect; prefer both dimensions odd."""
    if width_m <= 0 or height_m <= 0:
        raise ValueError("extent width and height must be positive")
    if width_m >= height_m:
        w = max_side
        h = max(1, int(round(max_side * height_m / width_m)))
        if h % 2 == 0:
            h = h + 1 if h < max_side else h - 1
            h = max(1, h)
    else:
        h = max_side
        w = max(1, int(round(max_side * width_m / height_m)))
        if w % 2 == 0:
            w = w + 1 if w < max_side else w - 1
            w = max(1, w)
    return w, h


def _utm_bounds(origin: Origin, extent: ExtentM) -> Tuple[float, float, float, float, Tuple[float, float]]:
    utm_origin = _utm_xy(origin.lon, origin.lat, origin.epsg)
    left = utm_origin[0] + extent.west
    bottom = utm_origin[1] + extent.south
    right = utm_origin[0] + extent.east
    top = utm_origin[1] + extent.north
    return left, bottom, right, top, utm_origin


def _extent_json(extent: ExtentM) -> dict:
    return extent.to_json()


def _write_meta_json(
    out_json: Path,
    *,
    size_px: Tuple[int, int],
    zmin_m: Optional[float],
    zmax_m: Optional[float],
    origin: Origin,
    utm_origin: Tuple[float, float],
    extent: ExtentM,
    meters_per_pixel: Tuple[float, float],
) -> None:
    payload = {
        "size_px": [int(size_px[0]), int(size_px[1])],
        "zmin_m": zmin_m,
        "zmax_m": zmax_m,
        "origin_wgs84": {
            "lon": origin.lon,
            "lat": origin.lat,
            "height_m": origin.height_m,
        },
        "utm_origin": [utm_origin[0], utm_origin[1]],
        "extent_m": _extent_json(extent),
        "meters_per_pixel": [meters_per_pixel[0], meters_per_pixel[1]],
        "crs_epsg": origin.epsg,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _meters_per_pixel(extent: ExtentM, size_px: Tuple[int, int]) -> Tuple[float, float]:
    nx = max(int(size_px[0]), 2)
    ny = max(int(size_px[1]), 2)
    return (
        extent.width / (nx - 1),
        extent.height / (ny - 1),
    )


def write_heightmap(
    dem_path: Path,
    origin: Origin,
    extent: ExtentM,
    out_png: Path,
    out_json: Path,
    *,
    max_side: int = _HEIGHTMAP_MAX_SIDE,
) -> RasterMeta:
    size_px = _odd_target_size(extent.width, extent.height, max_side)
    left, bottom, right, top, utm_origin = _utm_bounds(origin, extent)
    mpp = _meters_per_pixel(extent, size_px)
    dst_transform = from_origin(left, top, mpp[0], mpp[1])
    dst_crs = f"EPSG:{origin.epsg}"

    destination = np.full((size_px[1], size_px[0]), np.nan, dtype=np.float32)
    with rasterio.open(dem_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            src_nodata=src.nodata,
            dst_nodata=np.nan,
        )

    valid = destination[np.isfinite(destination)]
    if valid.size == 0:
        raise ValueError(f"no valid DEM samples in extent for {dem_path}")
    zmin_m = float(valid.min())
    zmax_m = float(valid.max())
    if zmax_m <= zmin_m:
        zmax_m = zmin_m + 1.0

    scaled = np.zeros((size_px[1], size_px[0]), dtype=np.uint16)
    mask = np.isfinite(destination)
    scaled[mask] = (
        ((destination[mask] - zmin_m) / (zmax_m - zmin_m) * 65535.0)
        .clip(0, 65535)
        .astype(np.uint16)
    )

    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(scaled, mode="I;16").save(out_png)

    _write_meta_json(
        out_json,
        size_px=size_px,
        zmin_m=zmin_m,
        zmax_m=zmax_m,
        origin=origin,
        utm_origin=utm_origin,
        extent=extent,
        meters_per_pixel=mpp,
    )
    return RasterMeta(
        size_px=size_px,
        zmin_m=zmin_m,
        zmax_m=zmax_m,
        origin=origin,
        utm_origin=utm_origin,
        extent_m=extent,
        meters_per_pixel=mpp,
        crs_epsg=origin.epsg,
        range_source="dem",
    )


def write_ortho(
    imagery_path: Path,
    origin: Origin,
    extent: ExtentM,
    out_png: Path,
    out_json: Path,
    max_dim: int = 8192,
) -> RasterMeta:
    long_side = max(4096, min(max_dim, 8192))
    size_px = _odd_target_size(extent.width, extent.height, long_side)
    left, bottom, right, top, utm_origin = _utm_bounds(origin, extent)
    dst_transform = from_bounds(left, bottom, right, top, size_px[0], size_px[1])
    dst_crs = f"EPSG:{origin.epsg}"

    with rasterio.open(imagery_path) as src:
        band_count = min(3, src.count) if src.count >= 1 else 0
        if band_count == 0:
            raise ValueError(f"imagery has no bands: {imagery_path}")
        bands = []
        for i in range(1, band_count + 1):
            destination = np.zeros((size_px[1], size_px[0]), dtype=np.float32)
            reproject(
                source=rasterio.band(src, i),
                destination=destination,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                src_nodata=src.nodata,
                dst_nodata=0,
            )
            bands.append(destination)
        while len(bands) < 3:
            bands.append(bands[-1].copy())

    rgb = np.stack(bands[:3], axis=-1)
    # Scale to 8-bit if source values exceed 255 (e.g. uint16 imagery)
    finite = rgb[np.isfinite(rgb)]
    vmax = float(finite.max()) if finite.size else 0.0
    if vmax > 255.0:
        rgb = (rgb / vmax * 255.0).clip(0, 255)
    rgb_u8 = np.nan_to_num(rgb, nan=0.0).clip(0, 255).astype(np.uint8)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb_u8, mode="RGB").save(out_png)

    mpp = _meters_per_pixel(extent, size_px)
    _write_meta_json(
        out_json,
        size_px=size_px,
        zmin_m=None,
        zmax_m=None,
        origin=origin,
        utm_origin=utm_origin,
        extent=extent,
        meters_per_pixel=mpp,
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
        range_source="dem",
    )


def _layer_from_sidecar(
    sidecar: Path | None,
    file_rel: Optional[str],
    *,
    encoding: str,
    sampling: str,
    extent: ExtentM,
) -> Optional[dict]:
    if not file_rel:
        return None
    size_px = None
    zmin_m = None
    zmax_m = None
    mpp = None
    if sidecar is not None and sidecar.is_file():
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        size_px = [int(data["size_px"][0]), int(data["size_px"][1])]
        zmin_m = data.get("zmin_m")
        zmax_m = data.get("zmax_m")
        if data.get("meters_per_pixel"):
            mpp = [float(data["meters_per_pixel"][0]), float(data["meters_per_pixel"][1])]
    if size_px and mpp is None:
        mpp = list(_meters_per_pixel(extent, (size_px[0], size_px[1])))
    nx, ny = (size_px[0], size_px[1]) if size_px else (0, 0)
    cell_m = (
        [extent.width / max(nx, 1), extent.height / max(ny, 1)] if size_px else None
    )
    layer = {
        "file": file_rel.replace("\\", "/"),
        "encoding": encoding,
        "sampling": sampling,
        "size_px": size_px,
        "vertex_spacing_m": mpp,
        "cell_size_m": cell_m,
        "pixel_0_0": "northwest",
        "column_axis": "east",
        "row_axis": "south",
    }
    if zmin_m is not None and zmax_m is not None:
        layer["zmin_m"] = float(zmin_m)
        layer["zmax_m"] = float(zmax_m)
        layer["decode_z_m"] = "zmin_m + (u16 / 65535) * (zmax_m - zmin_m)"
        layer["decode_z_usd_cm"] = "(decode_z_m) / meters_per_unit"
    if sampling == "vertex" and size_px and mpp:
        layer["pixel_to_xy_m"] = {
            "x_m": "extent.west + col * vertex_spacing_m[0]",
            "y_m": "extent.north - row * vertex_spacing_m[1]",
            "col_range": [0, size_px[0] - 1],
            "row_range": [0, size_px[1] - 1],
        }
    elif sampling == "cell" and size_px and cell_m:
        layer["pixel_to_xy_m"] = {
            "x_m": "extent.west + (col + 0.5) * cell_size_m[0]",
            "y_m": "extent.north - (row + 0.5) * cell_size_m[1]",
            "col_range": [0, size_px[0] - 1],
            "row_range": [0, size_px[1] - 1],
        }
    return layer


def _costmap_from_sidecar(
    sidecar: Path | None,
    occupancy_rel: Optional[str],
    cost_rel: Optional[str],
    extent: ExtentM,
) -> Optional[dict]:
    if not occupancy_rel and not cost_rel:
        return None
    data = {}
    if sidecar is not None and sidecar.is_file():
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    size_px = data.get("size_px")
    if size_px:
        size_px = [int(size_px[0]), int(size_px[1])]
    mpp = data.get("meters_per_pixel") or data.get("resolution_m")
    if isinstance(mpp, (int, float)):
        mpp = [float(mpp), float(mpp)]
    elif mpp:
        mpp = [float(mpp[0]), float(mpp[1])]
    coverage = data.get("coverage_m")
    if not coverage and size_px and mpp:
        coverage = {
            "west": float(extent.west),
            "south": float(extent.south),
            "east": float(extent.west) + size_px[0] * mpp[0],
            "north": float(extent.south) + size_px[1] * mpp[1],
            "width": size_px[0] * mpp[0],
            "height": size_px[1] * mpp[1],
        }
    res = float(mpp[0]) if mpp else None
    layer = {
        "occupancy_pgm": (occupancy_rel or "./nav2/connected/map.pgm").replace("\\", "/"),
        "cost_pgm": (cost_rel or "./nav2/connected/cost.pgm").replace("\\", "/"),
        "ros_yaml": "./nav2/connected/map_local.yaml",
        "meta_json": "./nav2/connected/map_meta.json",
        "format": "P5 8-bit",
        "sampling": "cell",
        "size_px": size_px,
        "resolution_m": res,
        "cell_size_m": mpp,
        "pixel_0_0": "northwest",
        "column_axis": "east",
        "row_axis": "south",
        "ros_origin_m": data.get("ros_origin_m")
        or [float(extent.west), float(extent.south), 0.0],
        "coverage_m": coverage,
        "occupancy_values": data.get("occupancy_values")
        or {"occupied": 0, "free": 254, "unknown": 205},
        "cost_values": data.get("cost_values")
        or {"free": 0, "lethal": 254, "unknown": 255},
        "note": (
            "Same CRS/origin/extent as DEM, ortho, and USD. "
            "Occupancy is ROS map_server. Cost is planner lethal/free/unknown. "
            "coverage_m may pad east/north to whole cells; west/south match the city extent."
        ),
    }
    if coverage and size_px and res:
        layer["pixel_to_xy_m"] = {
            "x_m": "coverage_m.west + (col + 0.5) * resolution_m",
            "y_m": "coverage_m.north - (row + 0.5) * resolution_m",
            "col_range": [0, size_px[0] - 1],
            "row_range": [0, size_px[1] - 1],
        }
        layer["pixel_to_usd_cm"] = {
            "x": "x_m / meters_per_unit",
            "y": "y_m / meters_per_unit",
            "z": 0,
        }
    return layer


def write_terrain_alignment(
    out_json: Path,
    *,
    scene_id: str,
    origin: Origin,
    extent: ExtentM,
    heightmap_rel: Optional[str] = None,
    ortho_rel: Optional[str] = None,
    pgm_rel: Optional[str] = None,
    cost_rel: Optional[str] = None,
    heightmap_meta_path: Optional[Path] = None,
    ortho_meta_path: Optional[Path] = None,
    pgm_meta_path: Optional[Path] = None,
    meters_per_unit: float = 1.0 / CM_PER_M,
    world_rel: str = "",
) -> Path:
    """Write one JSON that places heightmap + ortho in the USD city frame. No mesh."""
    utm_origin = _utm_xy(origin.lon, origin.lat, origin.epsg)
    mpu = float(meters_per_unit)
    cm = 1.0 / mpu
    x_min = extent.west * cm
    y_min = extent.south * cm
    x_max = extent.east * cm
    y_max = extent.north * cm
    payload = {
        "spec_version": "1.0",
        "scene_id": scene_id,
        "purpose": "Align DEM heightmap, ortho imagery, and machine cost/occupancy PGM to the USD city. Terrain is not a mesh.",
        "shared_frame": {
            "crs_epsg": int(origin.epsg),
            "origin_usd_cm": [0.0, 0.0, 0.0],
            "extent_m_is_common": True,
            "note": "DEM, ortho, cost/occupancy PGM, and USD share this origin, CRS, and extent. Pixel sizes differ per raster; convert with each layer's pixel_to_xy_m.",
        },
        "usd": {
            "world": world_rel or f"./World_{scene_id}.usda",
            "terrain_layer": "./layers/terrain.usda",
            "meters_per_unit": mpu,
            "up_axis": "Z",
            "axes": {"x": "east", "y": "north", "z": "up"},
            "origin": {
                "usd_cm": [0.0, 0.0, 0.0],
                "wgs84": {"lon": origin.lon, "lat": origin.lat, "height_m": origin.height_m},
                "utm": {"epsg": int(origin.epsg), "easting_m": utm_origin[0], "northing_m": utm_origin[1]},
            },
        },
        "extent_m": _extent_json(extent),
        "extent_usd_cm": {
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max,
            "width": extent.width * cm,
            "height": extent.height * cm,
            "center": [(x_min + x_max) / 2.0, (y_min + y_max) / 2.0, 0.0],
        },
        "city_geometry": {
            "z_usd_cm": 0.0,
            "note": "Roads and buildings are planar at Z=0. They are not draped on the DEM.",
        },
        "heightmap": _layer_from_sidecar(
            heightmap_meta_path,
            heightmap_rel,
            encoding="I;16 (0=zmin_m, 65535=zmax_m)",
            sampling="vertex",
            extent=extent,
        ),
        "ortho": _layer_from_sidecar(
            ortho_meta_path,
            ortho_rel,
            encoding="RGB8",
            sampling="cell",
            extent=extent,
        ),
        "costmap": _costmap_from_sidecar(pgm_meta_path, pgm_rel, cost_rel, extent),
        "unreal": {
            "place_at_usd_cm": [(x_min + x_max) / 2.0, (y_min + y_max) / 2.0, 0.0],
            "xy_size_cm": [extent.width * cm, extent.height * cm],
            "heightmap_not_ue_native": (
                "PNG 0 is zmin_m, not Unreal's 32768 mid. "
                "Z offset_cm = zmin_m / meters_per_unit; "
                "Z scale_cm = (zmax_m - zmin_m) / meters_per_unit if mapping 0..1 height."
            ),
        },
    }
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_json
