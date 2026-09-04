"""SceneData layout helpers (USDManager-oriented).

Layout::

    SceneData/{scene_id}/
      input/                 # osm, dem, imagery (scene-private)
      output/
        {scene_id}-USD/      # World, layers, textures, catalog, …
        {scene_id}-CostMap/
          2D/                # nav / PGM / yaml
          3D/                # reserved (external tools)
      backups/               # dated zips of previous output/

Shared assets live at tools/assets/ (not under SceneData).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


SCENE_DATA_DIRNAME = "SceneData"
TOOLS_ASSETS_REL = "tools/assets"


def scene_root(project_root: Path, scene_id: str) -> Path:
    return Path(project_root) / SCENE_DATA_DIRNAME / str(scene_id)


def scene_input_dir(project_root: Path, scene_id: str) -> Path:
    return scene_root(project_root, scene_id) / "input"


def usd_folder_name(scene_id: str) -> str:
    return f"{scene_id}-USD"


def costmap_folder_name(scene_id: str) -> str:
    return f"{scene_id}-CostMap"


def scene_usd_dir(project_root: Path, scene_id: str) -> Path:
    return scene_root(project_root, scene_id) / "output" / usd_folder_name(scene_id)


def scene_costmap_2d_dir(project_root: Path, scene_id: str) -> Path:
    return scene_root(project_root, scene_id) / "output" / costmap_folder_name(scene_id) / "2D"


def scene_costmap_3d_dir(project_root: Path, scene_id: str) -> Path:
    return scene_root(project_root, scene_id) / "output" / costmap_folder_name(scene_id) / "3D"


def tools_assets_dir(project_root: Path) -> Path:
    return Path(project_root) / "tools" / "assets"


def ensure_scene_output_dirs(project_root: Path, scene_id: str) -> dict[str, Path]:
    """Create {id}-USD + {id}-CostMap/2D + {id}-CostMap/3D (3D may be empty placeholder)."""
    paths = {
        "scene_root": scene_root(project_root, scene_id),
        "input": scene_input_dir(project_root, scene_id),
        "usd": scene_usd_dir(project_root, scene_id),
        "costmap_2d": scene_costmap_2d_dir(project_root, scene_id),
        "costmap_3d": scene_costmap_3d_dir(project_root, scene_id),
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
    keep = paths["costmap_3d"] / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    return paths


def costmap_rel_from_usd(rel_under_2d: str, scene_id: str) -> str:
    """USD-root relative path to a file under {scene_id}-CostMap/2D/."""
    rel = rel_under_2d.replace("\\", "/").lstrip("./")
    root = costmap_folder_name(scene_id)
    if rel.startswith(f"{root}/"):
        return f"../{rel}"
    if rel.startswith("CostMap/"):
        return f"../{root}/{rel[len('CostMap/') :]}"
    return f"../{root}/2D/{rel}"


def write_alignment_meta(
    path: Path,
    *,
    scene_id: str,
    origin_wgs84: dict[str, float],
    extent_m: dict[str, float],
    crs_epsg: int,
    resolution: dict[str, Any],
    usd_rel: Optional[str] = None,
    costmap_2d_rel: Optional[str] = None,
    costmap_3d_rel: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> Path:
    """Write scene alignment JSON shared by USD and CostMap consumers."""
    center = {
        "lon": float(origin_wgs84.get("lon", origin_wgs84.get("longitude", 0.0))),
        "lat": float(origin_wgs84.get("lat", origin_wgs84.get("latitude", 0.0))),
        "height_m": float(origin_wgs84.get("height_m", origin_wgs84.get("height", 0.0))),
    }
    usd = usd_rel or f"./output/{usd_folder_name(scene_id)}"
    cm2 = costmap_2d_rel or f"./output/{costmap_folder_name(scene_id)}/2D"
    cm3 = costmap_3d_rel or f"./output/{costmap_folder_name(scene_id)}/3D"
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "scene_id": scene_id,
        "crs": {"epsg": int(crs_epsg)},
        "center_wgs84": center,
        "extent_m": dict(extent_m),
        "resolution": dict(resolution),
        "paths": {
            "usd": usd.replace("\\", "/"),
            "costmap_2d": cm2.replace("\\", "/"),
            "costmap_3d": cm3.replace("\\", "/"),
        },
        "units": {"meters_per_unit_usd": 0.01, "up_axis": "Z"},
    }
    if extra:
        payload.update(extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
