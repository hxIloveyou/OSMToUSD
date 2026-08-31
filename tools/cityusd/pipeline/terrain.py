from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject

from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.rasters import write_heightmap, write_ortho, write_terrain_alignment
from cityusd.types import CM_PER_M, ExtentM, Origin

LogFn = Callable[[str], None]


def _resolve_input(cfg: PipelineConfig, key: str) -> Optional[Path]:
    block = cfg.inputs.get(key) or {}
    raw = block.get("path")
    if not raw:
        return None
    p = Path(str(raw)).expanduser()
    if not p.is_absolute():
        cand = (cfg.project_root / p).resolve()
        if cand.is_file():
            return cand
    return p if p.is_file() else p


def load_extent_context(package_dir: Path) -> tuple[dict, Origin, ExtentM]:
    extent_path = package_dir / "extent.json"
    if not extent_path.is_file():
        raise FileNotFoundError(f"Missing extent.json — run resolve_extent first: {extent_path}")
    payload = json.loads(extent_path.read_text(encoding="utf-8"))
    og = payload["origin_wgs84"]
    origin = Origin(
        lon=float(og["longitude"]),
        lat=float(og["latitude"]),
        height_m=float(og.get("height_m", og.get("height", 0.0))),
        epsg=int(payload["utm_epsg"]),
    )
    lm = payload["local_m"]
    extent = ExtentM(
        west=float(lm["min_x_m"]),
        south=float(lm["min_y_m"]),
        east=float(lm["max_x_m"]),
        north=float(lm["max_y_m"]),
    )
    return payload, origin, extent


def _resample_bilinear_u16(arr: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    h, w = arr.shape
    ys = np.linspace(0, h - 1, out_h)
    xs = np.linspace(0, w - 1, out_w)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    y0 = np.floor(yy).astype(int)
    x0 = np.floor(xx).astype(int)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    wy = yy - y0
    wx = xx - x0
    src = arr.astype(np.float64)
    out = (
        src[y0, x0] * (1 - wy) * (1 - wx)
        + src[y0, x1] * (1 - wy) * wx
        + src[y1, x0] * wy * (1 - wx)
        + src[y1, x1] * wy * wx
    )
    return np.clip(np.round(out), 0, 65535).astype(np.uint16)


def _write_ue_square_exports(
    rect_u16: np.ndarray,
    *,
    square_size: int,
    extent: ExtentM,
    zmin_m: float,
    zmax_m: float,
    out_png: Path,
    out_r16: Path,
    out_meta: Path,
    scene_id: str,
) -> dict[str, Any]:
    sq = _resample_bilinear_u16(rect_u16, square_size, square_size)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(sq, mode="I;16").save(out_png)
    out_r16.write_bytes(np.ascontiguousarray(sq, dtype="<u2").tobytes())

    zrange = max(zmax_m - zmin_m, 1e-6)
    nseg = square_size - 1
    scale_x = extent.width * CM_PER_M / nseg
    scale_y = extent.height * CM_PER_M / nseg
    scale_z = zrange * CM_PER_M / 512.0

    meta = {
        "schema_version": "0.2",
        "scene_id": scene_id,
        "size_px": [square_size, square_size],
        "zmin_m": zmin_m,
        "zmax_m": zmax_m,
        "extent_m": extent.to_json(),
        "ue_import": {
            "file": str(out_png).replace("\\", "/"),
            "r16": str(out_r16).replace("\\", "/"),
            "resolution": [square_size, square_size],
            "scale_x": round(scale_x, 4),
            "scale_y": round(scale_y, 4),
            "scale_z": round(scale_z, 4),
            "z_offset_cm": round(zmin_m * CM_PER_M, 4),
            "zscale_cm": round(zrange * CM_PER_M, 4),
            "note": "Square Landscape pixels; Scale X!=Y for rectangular world extent.",
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def _write_utm_geotiff(
    src_path: Path,
    *,
    origin: Origin,
    extent: ExtentM,
    out_path: Path,
    pixel_m: float,
    is_dem: bool,
) -> None:
    from cityusd.rasters import _utm_bounds

    left, bottom, right, top, _ = _utm_bounds(origin, extent)
    width = max(2, int(math.ceil((right - left) / pixel_m)))
    height = max(2, int(math.ceil((top - bottom) / pixel_m)))
    right = left + width * pixel_m
    top = bottom + height * pixel_m
    transform = from_bounds(left, bottom, right, top, width, height)
    dst_crs = f"EPSG:{origin.epsg}"
    dtype = "float32" if is_dem else "uint8"
    count = 1 if is_dem else 3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src_path) as src:
        if is_dem:
            dest = np.zeros((height, width), dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=dest,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )
            with rasterio.open(
                out_path,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype="float32",
                crs=dst_crs,
                transform=transform,
                compress="deflate",
            ) as dst:
                dst.write(dest.astype(np.float32), 1)
        else:
            bands = []
            band_count = min(3, src.count)
            for i in range(1, band_count + 1):
                dest = np.zeros((height, width), dtype=np.float32)
                reproject(
                    source=rasterio.band(src, i),
                    destination=dest,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )
                bands.append(dest)
            while len(bands) < 3:
                bands.append(bands[-1].copy())
            stack = np.stack(bands, axis=0)
            with rasterio.open(
                out_path,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=3,
                dtype="uint8",
                crs=dst_crs,
                transform=transform,
                compress="deflate",
            ) as dst:
                for i in range(3):
                    ch = stack[i]
                    vmax = float(np.nanmax(ch)) if ch.size else 255.0
                    if vmax > 255.0:
                        ch = (ch / vmax * 255.0).clip(0, 255)
                    dst.write(ch.astype(np.uint8), i + 1)


def run_terrain(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    step = cfg.step("terrain")
    if step is None:
        raise RuntimeError("terrain step missing from pipeline")
    step_cfg = load_step_config_ref(cfg, step, package_dir)

    _, origin, extent = load_extent_context(package_dir)
    outputs_cfg = step_cfg.get("outputs") or {}
    hm_cfg = step_cfg.get("heightmap") or {}
    ortho_cfg = step_cfg.get("ortho") or {}
    utm_pixel_m = float(step_cfg.get("utm_pixel_m", 10.0))
    square_ue = bool(hm_cfg.get("square_ue", True))
    square_size = int(hm_cfg.get("size", 2017))
    max_side = int(hm_cfg.get("max_side", square_size if square_ue else 2049))

    dem_path = _resolve_input(cfg, "dem")
    ortho_path = _resolve_input(cfg, "ortho")
    dem_optional = bool((cfg.inputs.get("dem") or {}).get("optional", False))

    if dem_path is None or not dem_path.is_file():
        if dem_optional:
            log("[terrain] skip — no DEM (optional)")
            return []
        raise FileNotFoundError(f"DEM required for terrain step: {dem_path}")

    written: list[str] = []

    # Rectangular heightmap (intermediate or final)
    rect_png = package_dir / "terrain" / "_heightmap_rect.png"
    rect_meta = package_dir / "terrain" / "_heightmap_rect_meta.json"
    log(f"[terrain] heightmap from {dem_path.name} (max_side={max_side})...")
    hm = write_heightmap(
        dem_path,
        origin,
        extent,
        rect_png,
        rect_meta,
        max_side=max_side,
    )

    out_png = package_dir / str(outputs_cfg.get("heightmap_png", "terrain/heightmap_ue.png"))
    out_r16 = package_dir / str(outputs_cfg.get("heightmap_r16", "terrain/heightmap_ue.r16"))
    out_hm_meta = package_dir / str(outputs_cfg.get("heightmap_meta", "terrain/heightmap_meta.json"))

    rect_u16 = np.array(Image.open(rect_png), dtype=np.uint16)
    zmin = float(hm.zmin_m or 0.0)
    zmax = float(hm.zmax_m or zmin + 1.0)

    if square_ue:
        log(f"[terrain] UE square export {square_size}x{square_size}...")
        _write_ue_square_exports(
            rect_u16,
            square_size=square_size,
            extent=extent,
            zmin_m=zmin,
            zmax_m=zmax,
            out_png=out_png,
            out_r16=out_r16,
            out_meta=out_hm_meta,
            scene_id=cfg.scene_id,
        )
    else:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rect_u16, mode="I;16").save(out_png)
        out_r16.write_bytes(np.ascontiguousarray(rect_u16, dtype="<u2").tobytes())
        meta = json.loads(rect_meta.read_text(encoding="utf-8"))
        meta["schema_version"] = "0.2"
        meta["scene_id"] = cfg.scene_id
        out_hm_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for rel in (out_png, out_r16, out_hm_meta):
        written.append(str(rel.relative_to(package_dir).as_posix()))

    dem_utm_rel = outputs_cfg.get("dem_utm")
    if dem_utm_rel:
        dem_utm = package_dir / dem_utm_rel
        log(f"[terrain] UTM DEM GeoTIFF @ {utm_pixel_m} m ...")
        _write_utm_geotiff(
            dem_path, origin=origin, extent=extent, out_path=dem_utm, pixel_m=utm_pixel_m, is_dem=True
        )
        written.append(str(Path(dem_utm_rel).as_posix()))

    ortho_rel_cfg = outputs_cfg.get("ortho_png", "terrain/ortho_ue.png")
    ortho_utm_rel = outputs_cfg.get("ortho_utm")
    if ortho_path and ortho_path.is_file():
        out_ortho = package_dir / ortho_rel_cfg
        out_ortho_meta = package_dir / "terrain" / "ortho_meta.json"
        max_dim = int(ortho_cfg.get("max_size_px", 4096))
        log(f"[terrain] ortho from {ortho_path.name} (max_dim={max_dim})...")
        write_ortho(ortho_path, origin, extent, out_ortho, out_ortho_meta, max_dim=max_dim)
        written.append(str(Path(ortho_rel_cfg).as_posix()))
        written.append("terrain/ortho_meta.json")
        if ortho_utm_rel:
            ortho_utm = package_dir / ortho_utm_rel
            log(f"[terrain] UTM ortho GeoTIFF @ {utm_pixel_m} m ...")
            _write_utm_geotiff(
                ortho_path,
                origin=origin,
                extent=extent,
                out_path=ortho_utm,
                pixel_m=utm_pixel_m,
                is_dem=False,
            )
            written.append(str(Path(ortho_utm_rel).as_posix()))
    else:
        log("[terrain] no ortho input — skip imagery")

    align_path = package_dir / "terrain" / "alignment.json"
    hm_rel = "./" + out_png.relative_to(package_dir).as_posix()
    ortho_meta_path = package_dir / "terrain" / "ortho_meta.json"
    write_terrain_alignment(
        align_path,
        scene_id=cfg.scene_id,
        origin=origin,
        extent=extent,
        heightmap_rel=hm_rel,
        ortho_rel=f"./{Path(ortho_rel_cfg).as_posix()}" if ortho_path and ortho_path.is_file() else None,
        heightmap_meta_path=out_hm_meta,
        ortho_meta_path=ortho_meta_path if ortho_meta_path.is_file() else None,
    )
    written.append("terrain/alignment.json")

    # Save resolved step config snapshot
    snap = package_dir / "configs" / "terrain.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/terrain.resolved.json")

    log(f"[terrain] ok → {len(written)} files under terrain/")
    return written
