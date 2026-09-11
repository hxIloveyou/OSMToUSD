"""Tests for pipeline nav_octomap step (mocked OctoMap build)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cityusd.pipeline.runner import run_pipeline
from cityusd.pipeline.schema import PipelineConfig, StepConfig


def _base_cfg(tmp_path: Path, osm_path: Path, dem_path: Path) -> PipelineConfig:
    root = Path(__file__).resolve().parents[1]
    return PipelineConfig(
        schema_version="0.3",
        scene_id="test_octo",
        scene_title="octo",
        scene_id_pattern="test_{timestamp}",
        frame={
            "origin_wgs84": {"longitude": 121.532933, "latitude": 25.047453, "height_m": 0},
            "utm_epsg": 32651,
            "extent": {
                "mode": "explicit",
                "explicit": {
                    "lon_west": 121.53,
                    "lon_east": 121.54,
                    "lat_south": 25.04,
                    "lat_north": 25.05,
                },
            },
        },
        inputs={
            "osm": {"path": str(osm_path), "optional": False},
            "dem": {"path": str(dem_path), "optional": False},
        },
        output_dir=tmp_path,
        output_layout="cityusd_v1",
        steps=[
            StepConfig(step="resolve_extent", enabled=True),
            StepConfig(step="nav_octomap", enabled=True, config_ref="nav_octomap.json"),
        ],
        runtime={"on_step_fail": "stop", "write_intermediate_configs": True},
        raw={},
        source_path=root / "configs" / "default" / "pipeline.yaml",
        project_root=root,
    )


def _write_tiny_dem(path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_bounds

    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = 8, 8
    data = np.full((h, w), 10.0, dtype=np.float32)
    transform = from_bounds(121.53, 25.04, 121.54, 25.05, w, h)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as ds:
        ds.write(data, 1)


def test_nav_octomap_writes_costmap_3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    osm_copy = tmp_path / "tiny.osm"
    osm_copy.write_text((root / "tests" / "fixtures" / "tiny.osm").read_text(encoding="utf-8"))
    dem_path = tmp_path / "tiny_dem.tif"
    _write_tiny_dem(dem_path)

    def _fake_build(cfg: dict):
        out_dir = Path(cfg["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = cfg["out_prefix"]
        bt = out_dir / f"{prefix}.bt"
        meta = out_dir / f"{prefix}_meta.json"
        bt.write_bytes(b"OCTOMAP_FAKE")
        meta.write_text(
            json.dumps(
                {
                    "origin": cfg.get("origin"),
                    "resolution": cfg.get("resolution"),
                    "occupied_voxels_total": 42,
                    "utm_zone": 51,
                    "elapsed_s": 0.1,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "meta": {"occupied_voxels_total": 42, "utm_zone": 51, "elapsed_s": 0.1},
            "outputs": {"bt": str(bt), "meta_json": str(meta)},
            "count": {},
        }

    monkeypatch.setattr("cityusd.pipeline.nav_octomap.build_costmap", _fake_build)
    monkeypatch.setattr(
        "cityusd.pipeline.nav_octomap.load_config",
        lambda path, overrides=None: dict(overrides or {}),
    )

    cfg = _base_cfg(tmp_path / "packages", osm_copy, dem_path)
    pkg = run_pipeline(cfg, only=["resolve_extent", "nav_octomap"])

    cost3 = cfg.costmap_3d_dir()
    bt = cost3 / "test_octo.bt"
    meta = cost3 / "test_octo_meta.json"
    assert bt.is_file()
    assert meta.is_file()
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["cityusd"]["scene_id"] == "test_octo"
    assert payload["cityusd"]["utm_epsg"] == 32651
    assert payload["origin"] is not None
    assert len(payload["origin"]) == 3

    snap = pkg / "configs" / "nav_octomap.resolved.json"
    assert snap.is_file()
    resolved = json.loads(snap.read_text(encoding="utf-8"))
    assert resolved["outputs"]["bt"] == "test_octo.bt"
    assert resolved["origin"] is not None
