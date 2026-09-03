"""SceneData layout helpers (USDManager-oriented).

Layout::

    SceneData/{scene_id}/
      input/                 # osm, dem, imagery (scene-private)
      output/
        USD/                 # World, layers, textures, catalog, …
        CostMap/
          2D/                # nav2 / PGM / yaml
          3D/                # reserved (external tools)

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


def scene_usd_dir(project_root: Path, scene_id: str) -> Path:
    return scene_root(project_root, scene_id) / "output" / "USD"


def scene_costmap_2d_dir(project_root: Path, scene_id: str) -> Path:
    return scene_root(project_root, scene_id) / "output" / "CostMap" / "2D"


def scene_costmap_3d_dir(project_root: Path, scene_id: str) -> Path:
    return scene_root(project_root, scene_id) / "output" / "CostMap" / "3D"


def tools_assets_dir(project_root: Path) -> Path:
    return Path(project_root) / "tools" / "assets"


def ensure_scene_output_dirs(project_root: Path, scene_id: str) -> dict[str, Path]:
    """Create USD + CostMap/2D + CostMap/3D (3D may be empty placeholder)."""
    paths = {
        "scene_root": scene_root(project_root, scene_id),
        "input": scene_input_dir(project_root, scene_id),
        "usd": scene_usd_dir(project_root, scene_id),
        "costmap_2d": scene_costmap_2d_dir(project_root, scene_id),
        "costmap_3d": scene_costmap_3d_dir(project_root, scene_id),
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
    # Explicit placeholder so empty 3D is visible in file managers / git.
    keep = paths["costmap_3d"] / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    return paths


def costmap_rel_from_usd(rel_under_2d: str) -> str:
    """USD-layer relative path to a file under CostMap/2D/."""
    rel = rel_under_2d.replace("\\", "/").lstrip("./")
    if rel.startswith("CostMap/"):
        return f"../{rel}"
    return f"../CostMap/2D/{rel}"


def write_alignment_meta(
    path: Path,
    *,
    scene_id: str,
    origin_wgs84: dict[str, float],
    extent_m: dict[str, float],
    crs_epsg: int,
    resolution: dict[str, Any],
    usd_rel: str = "./USD",
    costmap_2d_rel: str = "./CostMap/2D",
    costmap_3d_rel: str = "./CostMap/3D",
    extra: Optional[dict[str, Any]] = None,
) -> Path:
    """Write scene alignment JSON shared by USD and CostMap consumers."""
    center = {
        "lon": float(origin_wgs84.get("lon", origin_wgs84.get("longitude", 0.0))),
        "lat": float(origin_wgs84.get("lat", origin_wgs84.get("latitude", 0.0))),
        "height_m": float(origin_wgs84.get("height_m", origin_wgs84.get("height", 0.0))),
    }
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "scene_id": scene_id,
        "crs": {"epsg": int(crs_epsg)},
        "center_wgs84": center,
        "extent_m": dict(extent_m),
        "resolution": dict(resolution),
        "paths": {
            "usd": usd_rel.replace("\\", "/"),
            "costmap_2d": costmap_2d_rel.replace("\\", "/"),
            "costmap_3d": costmap_3d_rel.replace("\\", "/"),
        },
        "units": {"meters_per_unit_usd": 0.01, "up_axis": "Z"},
    }
    if extra:
        payload.update(extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
