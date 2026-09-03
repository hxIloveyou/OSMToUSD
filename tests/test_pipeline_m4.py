"""Integration tests for pipeline M4: overlay, assemble_world, package_zip."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from pxr import Usd, UsdGeom

from cityusd.package import WORLD_SUBLAYERS
from cityusd.pipeline.runner import run_pipeline
from cityusd.pipeline.schema import PipelineConfig, StepConfig


def _m4_cfg(tmp_path: Path, osm_path: Path) -> PipelineConfig:
    root = Path(__file__).resolve().parents[1]
    return PipelineConfig(
        schema_version="0.2",
        scene_id="test_m4",
        scene_title="m4",
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
                config_ref="configs/osm_taibei_ue.json",
            ),
            StepConfig(
                step="nav_pgm",
                enabled=True,
                config_ref="configs/nav_pgm_osm_only.json",
            ),
            StepConfig(
                step="overlay",
                enabled=True,
                config_ref="configs/overlay_default.json",
            ),
            StepConfig(
                step="assemble_world",
                enabled=True,
                config_ref="configs/world_cityusd_v1.json",
            ),
            StepConfig(
                step="package_zip",
                enabled=True,
                config_ref="configs/package_zip_default.json",
            ),
        ],
        runtime={"on_step_fail": "stop"},
        raw={},
        source_path=root / "examples" / "taibei_ue.pipeline.yaml",
        project_root=root,
    )


def test_m4_overlay_assemble_zip_tiny_osm(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    osm_copy = tmp_path / "tiny.osm"
    osm_copy.write_text((root / "tests" / "fixtures" / "tiny.osm").read_text(encoding="utf-8"))

    cfg = _m4_cfg(tmp_path / "packages", osm_copy)
    pkg = run_pipeline(
        cfg,
        only=["resolve_extent", "osm_city_usd", "nav_pgm", "overlay", "assemble_world", "package_zip"],
    )

    for name in (
        "equipment.usda",
        "infrastructure.usda",
        "obstacles_static.usda",
        "obstacles_dynamic.usda",
        "props.usda",
    ):
        assert (pkg / "overlay" / name).is_file()

    world = pkg / "World_test_m4.usda"
    assert world.is_file()
    stage = Usd.Stage.Open(str(world))
    assert stage.GetDefaultPrim().GetName() == "World"
    sublayers = list(stage.GetRootLayer().subLayerPaths)
    assert "./layers/city_roads.usdc" in sublayers or "./layers/city_roads.usda" in sublayers
    assert "./overlay/equipment.usda" in sublayers
    assert UsdGeom.GetStageMetersPerUnit(stage) == 0.01

    meta = json.loads((pkg / "meta.json").read_text(encoding="utf-8"))
    assert meta["spec_version"] == "1.0"
    assert meta["scene_id"] == "test_m4"
    assert "city_roads" in meta["layers"]
    assert meta.get("nav") is not None

    sources = json.loads((pkg / "sources_manifest.json").read_text(encoding="utf-8"))
    assert sources.get("osm")
    assert sources.get("extent") == "./extent.json"

    zip_path = cfg.scene_root() / "test_m4.zip"
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert any("USD/World_test_m4.usda" in n or n.endswith("World_test_m4.usda") for n in names)
    assert any(n.endswith("USD/meta.json") or n == "USD/meta.json" or "/meta.json" in n for n in names)
    assert "CostMap/2D/connected/map.pgm" in names

    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    for step in ("overlay", "assemble_world", "package_zip"):
        assert manifest["steps"][step]["status"] == "ok"

    assert len(sublayers) <= len(WORLD_SUBLAYERS)
