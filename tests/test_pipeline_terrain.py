"""Integration tests for pipeline terrain step (M1)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from cityusd.pipeline.runner import run_pipeline
from cityusd.pipeline.schema import PipelineConfig, StepConfig, load_pipeline_config


def _write_synthetic_dem(path: Path) -> None:
    """Small WGS84 DEM patch (~2km) for pipeline tests."""
    west, south, east, north = 121.50, 25.04, 121.52, 25.06
    w, h = 40, 40
    transform = from_bounds(west, south, east, north, w, h)
    elev = np.linspace(10, 80, w * h, dtype=np.float32).reshape(h, w)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=w,
        height=h,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(elev, 1)


def _minimal_terrain_cfg(tmp_path: Path, dem_path: Path) -> PipelineConfig:
    return PipelineConfig(
        schema_version="0.2",
        scene_id="test_terrain_m1",
        scene_title="terrain test",
        scene_id_pattern="test_{timestamp}",
        frame={
            "origin_wgs84": {"longitude": 121.51, "latitude": 25.05, "height_m": 0},
            "utm_epsg": 32651,
            "extent": {
                "mode": "explicit",
                "explicit": {
                    "lon_west": 121.50,
                    "lon_east": 121.52,
                    "lat_south": 25.04,
                    "lat_north": 25.06,
                },
            },
        },
        inputs={
            "dem": {"path": str(dem_path), "optional": False},
            "ortho": {"optional": True},
        },
        output_dir=tmp_path,
        output_layout="cityusd_v1",
        steps=[
            StepConfig(step="resolve_extent", enabled=True),
            StepConfig(
                step="terrain",
                enabled=True,
                depends_on=["resolve_extent"],
                config_ref="terrain.json",
            ),
        ],
        runtime={"on_step_fail": "stop"},
        raw={},
        source_path=Path(__file__).resolve().parents[1] / "examples" / "taibei_ue.pipeline.yaml",
        project_root=Path(__file__).resolve().parents[1],
    )


def test_terrain_step_produces_ue_heightmap(tmp_path: Path) -> None:
    dem = tmp_path / "fixtures" / "test_dem.tif"
    _write_synthetic_dem(dem)
    cfg = _minimal_terrain_cfg(tmp_path / "packages", dem)

    pkg = run_pipeline(cfg, only=["resolve_extent", "terrain"])
    assert (pkg / "extent.json").is_file()
    assert (pkg / "terrain" / "heightmap_ue.r16").is_file()
    assert (pkg / "terrain" / "heightmap_ue.png").is_file()
    assert (pkg / "terrain" / "heightmap_meta.json").is_file()
    assert (pkg / "terrain" / "dem_utm.tif").is_file()
    assert (pkg / "terrain" / "alignment.json").is_file()

    meta = json.loads((pkg / "terrain" / "heightmap_meta.json").read_text(encoding="utf-8"))
    ue = meta["ue_import"]
    assert ue["resolution"] == [2017, 2017]
    assert ue["scale_x"] != ue["scale_y"]
    assert ue["scale_z"] > 0

    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["steps"]["terrain"]["status"] == "ok"


def test_terrain_requires_extent(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    _write_synthetic_dem(dem)
    cfg = _minimal_terrain_cfg(tmp_path, dem)
    cfg.steps = [cfg.steps[1]]  # terrain only
    with pytest.raises(FileNotFoundError, match="extent.json"):
        run_pipeline(cfg, only=["terrain"])
