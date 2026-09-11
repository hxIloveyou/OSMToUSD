# 中文说明：从 AssetLibrary/materials/roads 安装路面与箭头 albedo。
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

# OSM texture key → candidate paths under materials/roads (first hit wins)
ROAD_SURFACE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "highway": (
        "RoadSurfaces/T_RoadSurf_Asphalt_Highway_D.png",
        "expressway.jpg",
        "highway.jpg",
        "roads_asphalt.jpg",
    ),
    "expressway": (
        "RoadSurfaces/T_RoadSurf_Asphalt_New_D.png",
        "expressway.jpg",
        "roads_asphalt.jpg",
    ),
    "national": (
        "RoadSurfaces/T_RoadSurf_Asphalt_Worn_D.png",
        "provincial.jpg",
        "asphalt.jpg",
    ),
    "provincial": (
        "RoadSurfaces/T_RoadSurf_Asphalt_Cracked_D.png",
        "provincial.jpg",
        "asphalt.jpg",
    ),
    "county": (
        "RoadSurfaces/T_RoadSurf_Asphalt_Wet_D.png",
        "county.jpg",
        "asphalt.jpg",
    ),
    "asphalt": (
        "RoadSurfaces/T_RoadSurf_Asphalt_Worn_D.png",
        "asphalt.jpg",
        "roads_asphalt.jpg",
    ),
    "cement": (
        "RoadSurfaces/T_RoadSurf_Concrete_Smooth_D.png",
        "pavement.jpg",
        "roads_pavement.jpg",
    ),
    "pavement": (
        "RoadSurfaces/T_RoadSurf_Concrete_Slab_D.png",
        "RoadSurfaces/T_RoadSurf_Brick_Grey_D.png",
        "pavement.jpg",
        "roads_pavement.jpg",
    ),
    "dirt": (
        "RoadSurfaces/T_RoadSurf_Dirt_Packed_D.png",
        "RoadSurfaces/T_RoadSurf_Dirt_D.png",
        "gravel.jpg",
    ),
    "path": (
        "RoadSurfaces/T_RoadSurf_Dirt_D.png",
        "gravel.jpg",
    ),
    "gravel": (
        "RoadSurfaces/T_RoadSurf_Gravel_D.png",
        "gravel.jpg",
    ),
}

# Decal kind → AssetLibrary marking files (tip assumed upward in texture)
ARROW_KIND_CANDIDATES: dict[str, tuple[str, ...]] = {
    "straight": (
        "RoadMarkings/T_RoadMark_Arrow_Straight.png",
        "marking_arrow_straight.jpg",
    ),
    "left": (
        "RoadMarkings/T_RoadMark_Arrow_Left.png",
        "marking_arrow_left.jpg",
    ),
    "right": (
        "RoadMarkings/T_RoadMark_Arrow_Right.png",
        "marking_arrow_right.jpg",
    ),
    "straight_left": (
        "RoadMarkings/T_RoadMark_Arrow_StraightLeft.png",
        "marking_arrow_straight_left.jpg",
    ),
    "straight_right": (
        "RoadMarkings/T_RoadMark_Arrow_StraightRight.png",
        "marking_arrow_straight_right.jpg",
    ),
    "left_right": (
        "RoadMarkings/T_RoadMark_Arrow_LeftRight.png",
        "marking_arrow_all.jpg",
        "roads_stop_arrows_all.jpg",
    ),
    "uturn": (
        "RoadMarkings/T_RoadMark_Arrow_UTurn.png",
        "marking_arrow_uturn.jpg",
    ),
    "straight_uturn": (
        "RoadMarkings/T_RoadMark_Arrow_StraightUTurn.png",
        "marking_arrow_straight.jpg",
    ),
    "merge_left": (
        "RoadMarkings/T_RoadMark_Arrow_MergeLeft.png",
        "marking_arrow_left.jpg",
    ),
    "merge_right": (
        "RoadMarkings/T_RoadMark_Arrow_MergeRight.png",
        "marking_arrow_right.jpg",
    ),
    "all": (
        "marking_arrow_all.jpg",
        "roads_stop_arrows_all.jpg",
        "RoadMarkings/T_RoadMark_Arrow_LeftRight.png",
    ),
}

ARROW_KIND_ORDER: tuple[str, ...] = (
    "straight",
    "left",
    "right",
    "straight_left",
    "straight_right",
    "left_right",
    "uturn",
    "straight_uturn",
    "merge_left",
    "merge_right",
    "all",
)

ROAD_SURFACE_KEYS: tuple[str, ...] = tuple(ROAD_SURFACE_CANDIDATES.keys())


def materials_roads_dir(library_dir: Path | None) -> Path | None:
    if library_dir is None:
        return None
    root = Path(library_dir) / "materials" / "roads"
    return root if root.is_dir() else None


def _find_candidate(roads_root: Path, rels: tuple[str, ...]) -> Path | None:
    for rel in rels:
        path = roads_root / rel
        if path.is_file():
            return path
    return None


def _install_albedo(src: Path, dest: Path, *, rgba: bool = False) -> Path:
    """Copy/convert image into package textures (PNG)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    if src.suffix.lower() == ".png" and not rgba:
        shutil.copy2(src, dest)
        return dest
    img = Image.open(src)
    img = img.convert("RGBA" if rgba else "RGB")
    img.save(dest)
    return dest


def install_road_library_textures(
    textures_dir: Path,
    library_dir: Path | None,
) -> dict[str, Path]:
    """功能：把 AssetLibrary 道路/箭头贴图装到 textures/{roads,furniture}/。

    返回已安装的 key→path；缺文件的 key 不出现（调用方回退程序化）。
    """
    roads_root = materials_roads_dir(library_dir)
    if roads_root is None:
        return {}

    textures_dir = Path(textures_dir)
    out: dict[str, Path] = {}
    road_dest = textures_dir / "roads"
    furn_dest = textures_dir / "furniture"

    for key, rels in ROAD_SURFACE_CANDIDATES.items():
        src = _find_candidate(roads_root, rels)
        if src is None:
            continue
        out[key] = _install_albedo(src, road_dest / f"{key}.png", rgba=False)

    for kind, rels in ARROW_KIND_CANDIDATES.items():
        src = _find_candidate(roads_root, rels)
        if src is None:
            continue
        out[f"arrow_{kind}"] = _install_albedo(
            src, furn_dest / f"arrow_{kind}.png", rgba=True
        )
    return out
