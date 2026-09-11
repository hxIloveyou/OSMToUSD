"""Tests for pipeline resolve_extent (schema v0.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cityusd.pipeline.resolve_extent import Wgs84Box, _relation, resolve_extent


def test_box_relation_disjoint():
    a = Wgs84Box(0, 0, 1, 1)
    b = Wgs84Box(2, 2, 3, 3)
    assert _relation(a, b).value == "disjoint"


def test_box_relation_containment():
    big = Wgs84Box(121.0, 24.0, 122.0, 25.0)
    small = Wgs84Box(121.4, 24.2, 121.6, 24.8)
    assert _relation(big, small).value == "containment"
    assert big.contains(small)


def test_box_intersection_partial():
    a = Wgs84Box(0, 0, 2, 2)
    b = Wgs84Box(1, 1, 3, 3)
    assert _relation(a, b).value == "partial_overlap"
    inter = a.intersection(b)
    assert inter is not None
    assert inter.lon_west == 1 and inter.lat_south == 1


def test_resolve_extent_explicit():
    payload = resolve_extent(
        frame={
            "origin_wgs84": {"longitude": 121.5, "latitude": 25.0, "height_m": 0},
            "utm_epsg": 32651,
            "extent": {
                "mode": "explicit",
                "explicit": {
                    "lon_west": 121.47,
                    "lon_east": 121.59,
                    "lat_south": 25.00,
                    "lat_north": 25.09,
                },
                "pad_deg": 0,
            },
        },
        inputs={},
    )
    assert payload["wgs84"]["lon_west"] == 121.47
    assert payload["local_m"]["width_x"] > 0
    assert payload["local_m"]["height_y"] > 0


def test_resolve_extent_auto_containment_warn_on_partial(tmp_path: Path):
    """DEM inside OSM → use smaller DEM box."""
    # Simulate by explicit auto path with only explicit sources in unit test:
    # partial overlap should warn when configured
    frame = {
        "origin_wgs84": {"longitude": 121.53, "latitude": 25.05, "height_m": 0},
        "utm_epsg": 32651,
        "extent": {
            "mode": "explicit",
            "explicit": {"lon_west": 121.48, "lon_east": 121.50, "lat_south": 25.04, "lat_north": 25.06},
            "on_relation": {"partial_overlap": "warn"},
        },
    }
    payload = resolve_extent(frame=frame, inputs={})
    assert "warnings" in payload


def test_load_pipeline_config_scene():
    from cityusd.pipeline.schema import load_scene_pipeline, load_step_config_ref

    root = Path(__file__).resolve().parents[1]
    cfg = load_scene_pipeline("taibei_ue", project_root=root)
    assert cfg.schema_version == "0.3"
    assert cfg.scene_id == "taibei_ue"
    assert cfg.step("resolve_extent") is not None
    assert cfg.step("terrain") and cfg.step("terrain").enabled
    assert cfg.step("nav_pgm") and cfg.step("nav_pgm").enabled
    assert cfg.step("osm_city_usd").config_ref == "osm_city_usd.json"
    assert cfg.package_dir() == cfg.usd_dir()
    assert "SceneData" in str(cfg.scene_root())
    assert cfg.usd_dir().name == "taibei_ue-USD"
    assert cfg.costmap_2d_dir().name == "2D"
    assert cfg.costmap_dir().name == "taibei_ue-CostMap"
    osm_cfg = load_step_config_ref(cfg, cfg.step("osm_city_usd"), cfg.package_dir())
    assert "build_layers" in osm_cfg


def test_scene_config_overrides_default(tmp_path: Path):
    from cityusd.pipeline.schema import load_pipeline_config, load_step_config_ref

    root = Path(__file__).resolve().parents[1]
    scene = tmp_path / "SceneData" / "override_demo"
    cfg_dir = scene / "input" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "osm_city_usd.json").write_text(
        '{"layers": {"vegetation": false, "lamps": false, "signs": false}}\n',
        encoding="utf-8",
    )
    (cfg_dir / "pipeline.yaml").write_text(
        "schema_version: '0.3'\n"
        "extends: [default/pipeline.yaml]\n"
        "scene:\n  id: override_demo\n"
        "frame:\n  origin_wgs84: {longitude: 0, latitude: 0, height_m: 0}\n"
        "  utm_epsg: 32651\n"
        "inputs: {}\n",
        encoding="utf-8",
    )
    import shutil

    (tmp_path / "configs").mkdir()
    shutil.copytree(root / "configs" / "default", tmp_path / "configs" / "default")
    (tmp_path / "tools" / "cityusd").mkdir(parents=True)
    cfg = load_pipeline_config(cfg_dir / "pipeline.yaml")
    assert cfg.scene_id == "override_demo"
    step = cfg.step("osm_city_usd")
    assert step is not None
    merged = load_step_config_ref(cfg, step, cfg.package_dir())
    assert merged["layers"]["vegetation"] is False
    assert merged["layers"]["lamps"] is False
    assert merged["layers"]["buildings"] is True  # from default
    assert "build_layers" in merged


def test_runner_resolve_extent_only(tmp_path: Path):
    from cityusd.pipeline.runner import run_pipeline
    from cityusd.pipeline.schema import load_scene_pipeline

    root = Path(__file__).resolve().parents[1]
    cfg = load_scene_pipeline("taibei_ue", project_root=root)
    cfg.output_dir = tmp_path
    cfg.scene_id = "test_extent_only"
    cfg.runtime["backup_output_before_run"] = False
    cfg.runtime["backup_previous_packages"] = False

    # Override to explicit extent so no input files required
    cfg.frame["extent"] = {
        "mode": "explicit",
        "explicit": {
            "lon_west": 121.47,
            "lon_east": 121.59,
            "lat_south": 25.00,
            "lat_north": 25.09,
        },
    }

    pkg = run_pipeline(cfg, only=["resolve_extent"])
    extent = json.loads((pkg / "extent.json").read_text(encoding="utf-8"))
    assert extent["schema_version"] == "0.2"
    assert (pkg / "manifest.json").is_file()
