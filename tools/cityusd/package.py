# 中文说明：Scene Package 元数据、World 子层、overlay 空层与打包辅助。
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from pxr import Kind, Usd, UsdGeom

from cityusd.buildings import LOD_LEVELS
from cityusd.furniture import (
    placeholder_lamp_parts,
    placeholder_sign_parts,
    placeholder_tree_parts,
)
from cityusd.usd_write import configure_stage, write_multipart_prototype_layer

WORLD_SUBLAYERS = [
    "./layers/environment.usda",
    "./layers/terrain.usda",
    "./layers/nav.usda",
    "./layers/city_water.usdc",
    "./layers/city_vegetation.usdc",
    "./layers/city_roads.usdc",
    "./layers/city_buildings.usdc",
    "./layers/city_lamps.usdc",
    "./layers/city_signs.usdc",
    "./overlay/equipment.usda",
    "./overlay/infrastructure.usda",
    "./overlay/obstacles_static.usda",
    "./overlay/obstacles_dynamic.usda",
    "./overlay/props.usda",
]

OVERLAY_LAYERS = [
    ("equipment.usda", "Equipment"),
    ("infrastructure.usda", "Infrastructure"),
    ("obstacles_static.usda", "ObstaclesStatic"),
    ("obstacles_dynamic.usda", "ObstaclesDynamic"),
    ("props.usda", "Props"),
]


def write_empty_overlay(path: Path, prim_name: str) -> None:
    stage = configure_stage(path)
    UsdGeom.Xform.Define(stage, "/World/Overlay")
    UsdGeom.Xform.Define(stage, f"/World/Overlay/{prim_name}")
    stage.GetRootLayer().Save()


def write_all_overlays(overlay_dir: Path) -> list[Path]:
    overlay_dir = Path(overlay_dir)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, prim_name in OVERLAY_LAYERS:
        dest = overlay_dir / filename
        write_empty_overlay(dest, prim_name)
        written.append(dest)
    return written


CITY_FOLDERS = ("Roads", "Buildings", "Water", "Vegetation", "Lamps", "Signs")


def write_world(path: Path, scene_id: str, sublayers: list[str]) -> None:
    """Root stage with an explicit City skeleton so UE Outliner shows folders.

功能：写出 World USD（子层列表）。
"""
    stage = configure_stage(path)
    root = stage.GetRootLayer()
    root.subLayerPaths = list(sublayers)
    world = stage.GetDefaultPrim()
    world.SetCustomData({"scene_id": scene_id})
    Usd.ModelAPI(world).SetKind(Kind.Tokens.assembly)
    city = UsdGeom.Xform.Define(stage, "/World/City")
    Usd.ModelAPI(city.GetPrim()).SetKind(Kind.Tokens.group)
    for name in CITY_FOLDERS:
        xf = UsdGeom.Xform.Define(stage, f"/World/City/{name}")
        Usd.ModelAPI(xf.GetPrim()).SetKind(Kind.Tokens.group)
    for path_name in ("/World/Environment", "/World/Terrain", "/World/Nav", "/World/Overlay"):
        xf = UsdGeom.Xform.Define(stage, path_name)
        Usd.ModelAPI(xf.GetPrim()).SetKind(Kind.Tokens.group)
    root.Save()


def write_meta(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_package_meta(
    scene_id: str,
    crs: Optional[dict] = None,
    **overrides,
) -> dict:
    """功能：构建 package meta 字典。"""
    payload = {
        "spec_version": "1.0",
        "scene_id": scene_id,
        "crs": crs or {},
        "units": {"meters_per_unit": 0.01, "up_axis": "Z"},
        "layers": {
            "environment": "./layers/environment.usda",
            "terrain": "./layers/terrain.usda",
            "nav": "./layers/nav.usda",
            "city_water": "./layers/city_water.usdc",
            "city_vegetation": "./layers/city_vegetation.usdc",
            "city_roads": "./layers/city_roads.usdc",
            "city_buildings": "./layers/city_buildings.usdc",
            "city_lamps": "./layers/city_lamps.usdc",
            "city_signs": "./layers/city_signs.usdc",
        },
        "overlay": {
            "equipment": "./overlay/equipment.usda",
            "infrastructure": "./overlay/infrastructure.usda",
            "obstacles_static": "./overlay/obstacles_static.usda",
            "obstacles_dynamic": "./overlay/obstacles_dynamic.usda",
            "props": "./overlay/props.usda",
        },
        "lod": [dict(level) for level in LOD_LEVELS],
        "vegetation_instancer": True,
        "lamp_instancer": True,
        "sign_instancer": True,
        "prototype_swap": True,
        "capabilities": {
            "has_building_lod": True,
            "building_mesh_mode": "closed_mesh_geomsubset",
            "distance_cull_metadata": True,
        },
    }
    payload.update(overrides)
    return payload


def write_prototype_files(models_dir: Path, proto_tex: Optional[dict[str, str]] = None) -> tuple[Path, Path, Path]:
    proto_dir = Path(models_dir) / "prototypes"
    proto_dir.mkdir(parents=True, exist_ok=True)
    tree_path = proto_dir / "tree.usda"
    lamp_path = proto_dir / "lamp.usda"
    sign_path = proto_dir / "sign.usda"
    proto_tex = proto_tex or {}

    def _parts(raw: list[dict], prim: str, tex_map: dict[str, str], extra: dict | None = None) -> list[dict]:
        extra = extra or {}
        out = []
        for part in raw:
            name = part["name"]
            item = dict(part)
            item["material_path"] = f"/{prim}/Looks/{name}"
            tex_key = tex_map.get(name)
            if tex_key and tex_key in proto_tex:
                item["texture_path"] = proto_tex[tex_key]
            if name in extra:
                item.update(extra[name])
            out.append(item)
        return out

    write_multipart_prototype_layer(
        tree_path,
        "TreePlaceholder",
        _parts(placeholder_tree_parts(), "TreePlaceholder", {"Trunk": "bark", "Crown": "foliage"}),
    )
    write_multipart_prototype_layer(
        lamp_path,
        "LampPlaceholder",
        _parts(
            placeholder_lamp_parts(),
            "LampPlaceholder",
            {
                "Base": "metal",
                "Pole": "metal",
                "Collar": "metal",
                "Arm": "metal",
                "Head": "lamp_head",
                "Glass": "lamp_head",
            },
            extra={
                "Head": {"emissive_rgb": (1.0, 0.75, 0.15), "roughness": 0.35},
                "Glass": {"emissive_rgb": (1.0, 0.85, 0.35), "roughness": 0.2},
            },
        ),
    )
    write_multipart_prototype_layer(
        sign_path,
        "SignPlaceholder",
        _parts(
            placeholder_sign_parts(),
            "SignPlaceholder",
            {"Post": "metal", "Board": "sign_board", "Cap": "metal"},
        ),
    )
    return tree_path, lamp_path, sign_path


_LAYER_USD_RELS = {
    "water": ("layers/city_water.usdc", "layers/city_water.usda"),
    "vegetation": (
        "layers/city_vegetation.usdc",
        "layers/city_vegetation.usda",
        "models/prototypes/tree.usda",
    ),
    "roads": ("layers/city_roads.usdc", "layers/city_roads.usda"),
    "buildings": ("layers/city_buildings.usdc", "layers/city_buildings.usda"),
    "lamps": (
        "layers/city_lamps.usdc",
        "layers/city_lamps.usda",
        "models/prototypes/lamp.usda",
    ),
    "signs": (
        "layers/city_signs.usdc",
        "layers/city_signs.usda",
        "models/prototypes/sign.usda",
    ),
    "nav": ("layers/nav.usda",),
    "terrain": ("layers/terrain.usda",),
    "world": (
        "layers/environment.usda",
        "overlay/equipment.usda",
        "overlay/infrastructure.usda",
        "overlay/obstacles_static.usda",
        "overlay/obstacles_dynamic.usda",
        "overlay/props.usda",
    ),
}


def usd_files_to_backup(out_dir: Path, layers: set[str], scene_id: str) -> list[Path]:
    """Existing USD files this build is about to overwrite."""
    out_dir = Path(out_dir)
    rels: list[str] = []
    for key in layers:
        rels.extend(_LAYER_USD_RELS.get(key, ()))
    if "world" in layers and scene_id:
        rels.append(f"World_{scene_id}.usda")
    found: list[Path] = []
    seen: set[Path] = set()
    for rel in rels:
        path = out_dir / rel
        try:
            key = path.resolve()
        except OSError:
            key = path
        if path.is_file() and key not in seen:
            seen.add(key)
            found.append(path)
    return found


def backup_existing_usd(out_dir: Path, layers: set[str], scene_id: str) -> Path | None:
    """Zip previous USD for the layers this run will rewrite. None if nothing exists yet."""
    files = usd_files_to_backup(out_dir, layers, scene_id)
    if not files:
        return None
    out_dir = Path(out_dir)
    backup_dir = out_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "-".join(sorted(layers)) or "usd"
    zip_path = backup_dir / f"usd_{stamp}_{tag}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(out_dir).as_posix())
    return zip_path
