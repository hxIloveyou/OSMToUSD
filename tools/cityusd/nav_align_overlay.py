"""Debug-only PGM↔USD alignment overlay (NOT for production World).

Writes under ``debug/nav_align/``:
  - align_preview.png  — free=green, occupied=red, unknown=transparent-ish
  - nav_align_overlay.usda — textured plane in local cm (same frame as city)

Never composed into World_*.usda. Disable via nav_pgm config::

    "align_overlay": { "enabled": false }

Production zip should exclude ``debug/**``.
"""
# 中文说明：调试用 PGM↔USD 对齐叠加（不进正式 World）。

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from pxr import Gf, Sdf, UsdGeom, UsdShade

from cityusd.pgm import FREE, OCCUPIED, UNKNOWN
from cityusd.types import CM_PER_M, ExtentM
from cityusd.usd_write import configure_stage, write_preview_material

DEBUG_REL_DIR = "debug/nav_align"
README_NAME = "README.txt"

_README = """\
DEBUG ONLY — Nav PGM ↔ USD road alignment overlay
=================================================
DO NOT ship this folder in production Scene Packages.

Contents
  align_preview.png       Colored occupancy (free=green, occupied=red)
  nav_align_overlay.usda  Plane in the same local cm frame as city roads

How to view in UE / usdview
  1. Open World_*.usda as usual.
  2. ALSO open (or add as a temporary subLayer):
       debug/nav_align/nav_align_overlay.usda
  3. Green bands should sit on motor roads; red on buildings/water.
  4. Check center AND map edges — residuals should not grow with distance.

Disable generation (production builds)
  configs/default/nav_pgm.json → "align_overlay": { "enabled": false }
  package_zip exclude already drops debug/** when configured.

Remove from an existing package
  Delete the entire debug/ directory.
"""


def read_pgm_u8(path: Path) -> np.ndarray:
    """Load P5 PGM → uint8 array (ny, nx), row 0 = north."""
    raw = Path(path).read_bytes()
    if not raw.startswith(b"P5"):
        raise ValueError(f"Not a binary PGM P5: {path}")
    # Skip magic + whitespace, parse width height maxval
    i = 2
    while i < len(raw) and raw[i] in b" \t\r\n":
        i += 1
    header_parts: list[int] = []
    while len(header_parts) < 3 and i < len(raw):
        if raw[i] == ord("#"):
            while i < len(raw) and raw[i] not in b"\r\n":
                i += 1
            continue
        start = i
        while i < len(raw) and raw[i] not in b" \t\r\n":
            i += 1
        token = raw[start:i].decode("ascii")
        if token:
            header_parts.append(int(token))
        while i < len(raw) and raw[i] in b" \t\r\n":
            i += 1
    if len(header_parts) < 3:
        raise ValueError(f"Bad PGM header: {path}")
    width, height, maxval = header_parts
    if maxval != 255:
        raise ValueError(f"Expected 8-bit PGM, maxval={maxval}: {path}")
    data = np.frombuffer(raw[i : i + width * height], dtype=np.uint8)
    if data.size != width * height:
        raise ValueError(f"PGM size mismatch: {path}")
    return data.reshape((height, width))


def colorize_occupancy(grid: np.ndarray) -> np.ndarray:
    """RGBA uint8: free green, occupied red, unknown faint gray.

    Free accepts both conventional Nav2 254 and downsampled-bundle 255.
    """
    ny, nx = grid.shape
    rgba = np.zeros((ny, nx, 4), dtype=np.uint8)
    free = (grid == FREE) | (grid == 255)
    occ = grid == OCCUPIED
    unk = ~(free | occ)
    rgba[free] = (40, 220, 80, 160)
    rgba[occ] = (220, 40, 40, 100)
    rgba[unk] = (180, 180, 180, 40)
    # Keep UNKNOWN token distinct if present
    rgba[grid == UNKNOWN] = (180, 180, 180, 40)
    return rgba


def _downscale_rgba(rgba: np.ndarray, max_side: int) -> np.ndarray:
    ny, nx = rgba.shape[:2]
    if max(ny, nx) <= max_side:
        return rgba
    scale = max_side / float(max(ny, nx))
    out_w = max(1, int(round(nx * scale)))
    out_h = max(1, int(round(ny * scale)))
    img = Image.fromarray(rgba, mode="RGBA")
    img = img.resize((out_w, out_h), Image.Resampling.NEAREST)
    return np.asarray(img)


def _coverage_from_meta(map_meta: dict, extent: ExtentM) -> dict:
    cov = map_meta.get("coverage_m")
    if isinstance(cov, dict) and "west" in cov:
        return cov
    return {
        "west": float(extent.west),
        "south": float(extent.south),
        "east": float(extent.east),
        "north": float(extent.north),
        "width": float(extent.width),
        "height": float(extent.height),
    }


def write_nav_align_overlay_usda(
    out_usda: Path,
    *,
    texture_rel: str,
    coverage_m: dict,
    z_cm: float = 50.0,
) -> None:
    """Textured plane: SW UV(0,0) … NE UV(1,1); PNG top = north → UV v=1."""
    west = float(coverage_m["west"]) * CM_PER_M
    south = float(coverage_m["south"]) * CM_PER_M
    east = float(coverage_m["east"]) * CM_PER_M
    north = float(coverage_m["north"]) * CM_PER_M
    z = float(z_cm)

    stage = configure_stage(out_usda)
    root = UsdGeom.Xform.Define(stage, "/World/DebugNavAlign")
    root.GetPrim().SetCustomData(
        {
            "purpose": "debug_pgm_usd_alignment",
            "production": "false",
            "note": "Remove debug/ before shipping. Not a World sublayer.",
        }
    )

    mat_path = "/World/DebugNavAlign/Looks/AlignPreview"
    write_preview_material(
        stage,
        mat_path,
        diffuse_rgb=(0.2, 0.8, 0.3),
        texture_path=texture_rel,
        roughness=1.0,
        wrap="clamp",
        opacity_from_alpha=True,
    )

    # SW, SE, NE, NW — UV v=0 south (image bottom), v=1 north (image top)
    points = [
        (west, south, z),
        (east, south, z),
        (east, north, z),
        (west, north, z),
    ]
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    mesh = UsdGeom.Mesh.Define(stage, "/World/DebugNavAlign/AlignPlane")
    mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in points])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    mesh.CreateDoubleSidedAttr(True)
    st = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex
    )
    st.Set([Gf.Vec2f(*uv) for uv in uvs])

    UsdShade.MaterialBindingAPI(mesh).Bind(UsdShade.Material.Get(stage, mat_path))
    stage.GetRootLayer().Save()


def write_nav_align_overlay(
    package_dir: Path,
    *,
    map_pgm: Path,
    map_meta_path: Path,
    extent: ExtentM,
    enabled: bool = True,
    max_preview_side: int = 4096,
    z_cm: float = 50.0,
    debug_rel_dir: str | None = None,
    label: str | None = None,
) -> list[str]:
    """Write debug overlay artifacts. Returns relative paths (empty if disabled)."""
    if not enabled:
        return []

    package_dir = Path(package_dir)
    rel_dir = (debug_rel_dir or DEBUG_REL_DIR).replace("\\", "/").strip("/")
    out_dir = package_dir / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    meta: dict = {}
    if map_meta_path.is_file():
        meta = json.loads(map_meta_path.read_text(encoding="utf-8"))
    coverage = _coverage_from_meta(meta, extent)

    grid = read_pgm_u8(map_pgm)
    rgba = colorize_occupancy(grid)
    rgba = _downscale_rgba(rgba, int(max_preview_side))

    png_path = out_dir / "align_preview.png"
    Image.fromarray(rgba, mode="RGBA").save(png_path)

    # Texture path relative to the USDA file location
    usda_path = out_dir / "nav_align_overlay.usda"
    write_nav_align_overlay_usda(
        usda_path,
        texture_rel="./align_preview.png",
        coverage_m=coverage,
        z_cm=z_cm,
    )

    tag = label or rel_dir
    readme = out_dir / README_NAME
    readme.write_text(
        _README.replace("debug/nav_align/nav_align_overlay.usda", f"{rel_dir}/nav_align_overlay.usda")
        + f"\nVariant label: {tag}\nSource PGM: {map_pgm.name}\n",
        encoding="utf-8",
    )

    marker = {
        "production": False,
        "compose_into_world": False,
        "label": tag,
        "debug_rel_dir": rel_dir,
        "source_pgm": str(Path(map_pgm).relative_to(package_dir).as_posix())
        if map_pgm.is_relative_to(package_dir)
        else str(map_pgm),
        "coverage_m": coverage,
        "preview_size_px": [int(rgba.shape[1]), int(rgba.shape[0])],
        "pgm_size_px": [int(grid.shape[1]), int(grid.shape[0])],
        "resolution_m": meta.get("resolution_m"),
        "z_cm": z_cm,
    }
    (out_dir / "overlay_meta.json").write_text(
        json.dumps(marker, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return [
        f"{rel_dir}/align_preview.png",
        f"{rel_dir}/nav_align_overlay.usda",
        f"{rel_dir}/{README_NAME}",
        f"{rel_dir}/overlay_meta.json",
    ]
