"""Integration tests for pipeline nav_pgm + osm_labels (M3)."""

from __future__ import annotations

import json
from pathlib import Path

from cityusd.pipeline.runner import run_pipeline
from cityusd.pipeline.schema import PipelineConfig, StepConfig


def _base_cfg(tmp_path: Path, osm_path: Path) -> PipelineConfig:
    root = Path(__file__).resolve().parents[1]
    return PipelineConfig(
        schema_version="0.2",
        scene_id="test_m3",
        scene_title="m3",
        scene_id_pattern="test_{timestamp}",
        frame={
            "origin_wgs84": {"longitude": 119.0004, "latitude": 36.00055, "height_m": 0},
            "utm_epsg": 32651,
            "extent": {
                "mode": "explicit",
                "explicit": {
                    "lon_west": 119.0,
                    "lon_east": 119.001,
                    "lat_south": 36.0,
                    "lat_north": 36.001,
                },
            },
        },
        inputs={"osm": {"path": str(osm_path), "optional": False}},
        output_dir=tmp_path,
        output_layout="cityusd_v1",
        steps=[
            StepConfig(step="resolve_extent", enabled=True),
            StepConfig(
                step="osm_labels",
                enabled=True,
                config_ref="configs/osm_labels_sharded.json",
            ),
            StepConfig(
                step="nav_pgm",
                enabled=True,
                config_ref="configs/nav_pgm_osm_only.json",
            ),
        ],
        runtime={"on_step_fail": "stop"},
        raw={},
        source_path=root / "examples" / "taibei_ue.pipeline.yaml",
        project_root=root,
    )


def test_nav_pgm_and_osm_labels_tiny(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    osm_copy = tmp_path / "tiny.osm"
    osm_copy.write_text((root / "tests" / "fixtures" / "tiny.osm").read_text(encoding="utf-8"))

    cfg = _base_cfg(tmp_path / "packages", osm_copy)
    pkg = run_pipeline(cfg, only=["resolve_extent", "osm_labels", "nav_pgm"])

    assert (pkg / "nav2" / "connected" / "map.pgm").is_file()
    assert (pkg / "nav2" / "connected" / "cost.pgm").is_file()
    assert (pkg / "nav2" / "connected" / "map_local.yaml").is_file()
    assert (pkg / "nav2" / "connected" / "valhalla_origin.yaml").is_file()
    assert (pkg / "layers" / "nav.usda").is_file()

    manifest = json.loads((pkg / "catalog" / "index" / "shard_manifest.json").read_text(encoding="utf-8"))
    assert manifest["feature_count"] >= 3
    assert manifest["shard_count"] >= 1
    shard_files = list((pkg / "catalog" / "shards").glob("lod0_*.json"))
    assert shard_files

    meta = json.loads((pkg / "nav2" / "connected" / "map_meta.json").read_text(encoding="utf-8"))
    assert meta["resolution_m"] == 1.0

    m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert m["steps"]["nav_pgm"]["status"] == "ok"
    assert m["steps"]["osm_labels"]["status"] == "ok"
