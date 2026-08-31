"""Integration tests for pipeline osm_city_usd step (M2)."""

from __future__ import annotations

import json
from pathlib import Path

from pxr import Usd, UsdGeom

from cityusd.pipeline.runner import run_pipeline
from cityusd.pipeline.schema import PipelineConfig, StepConfig


def _pipeline_cfg(tmp_path: Path, osm_path: Path) -> PipelineConfig:
    root = Path(__file__).resolve().parents[1]
    return PipelineConfig(
        schema_version="0.2",
        scene_id="test_osm_m2",
        scene_title="osm m2",
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
                step="osm_city_usd",
                enabled=True,
                depends_on=["resolve_extent"],
                config_ref="configs/osm_taibei_ue.json",
            ),
        ],
        runtime={"on_step_fail": "stop"},
        raw={},
        source_path=root / "examples" / "taibei_ue.pipeline.yaml",
        project_root=root,
    )


def test_osm_city_usd_step_tiny_osm(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests" / "fixtures" / "tiny.osm"
    osm_copy = tmp_path / "tiny.osm"
    osm_copy.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    cfg = _pipeline_cfg(tmp_path / "packages", osm_copy)
    pkg = run_pipeline(cfg, only=["resolve_extent", "osm_city_usd"])

    roads = pkg / "layers" / "city_roads.usdc"
    if not roads.is_file():
        roads = pkg / "layers" / "city_roads.usda"
    assert roads.is_file()

    bldg = pkg / "layers" / "city_buildings.usdc"
    if not bldg.is_file():
        bldg = pkg / "layers" / "city_buildings.usda"
    assert bldg.is_file()

    stats = json.loads((pkg / "layers" / "city_build_stats.json").read_text(encoding="utf-8"))
    assert stats["stats"]["roads"] >= 1
    assert stats["stats"]["buildings"] >= 1
    assert stats["range_source"] == "pipeline_extent"

    stage = Usd.Stage.Open(str(roads))
    meshes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
    assert meshes

    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["steps"]["osm_city_usd"]["status"] == "ok"

    meta = json.loads((pkg / "meta.json").read_text(encoding="utf-8"))
    assert meta.get("city_build") is not None
    assert not list(pkg.glob("World_*.usda"))
