"""Building tile payload export."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd, UsdGeom

from build_city_usd import main


def _tiny_data(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    (data / "osm").mkdir(parents=True)
    src = Path("tests/fixtures/tiny.osm")
    (data / "osm" / "tiny.osm").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return data, tmp_path / "out"


def test_buildings_tiles_default(tmp_path: Path) -> None:
    data, out = _tiny_data(tmp_path)
    assert main(["--data", str(data), "--output", str(out), "--scene-id", "tile_on", "--layers", "buildings"]) == 0
    tiles = list((out / "layers" / "tiles").glob("buildings_*.usdc"))
    assert tiles
    index = out / "layers" / "city_buildings.usdc"
    if not index.is_file():
        index = out / "layers" / "city_buildings.usda"
    stage = Usd.Stage.Open(str(index))
    root = stage.GetPrimAtPath("/World/City/Buildings")
    assert root.HasAuthoredPayloads()
    meshes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh) and "Looks" not in str(p.GetPath())]
    assert any(p.GetName() == "LOD0" for p in meshes)
    assert stage.GetPrimAtPath("/World/Looks/Building").IsValid()


def test_buildings_monolithic_flag(tmp_path: Path) -> None:
    data, out = _tiny_data(tmp_path)
    assert (
        main(
            [
                "--data",
                str(data),
                "--output",
                str(out),
                "--scene-id",
                "tile_off",
                "--layers",
                "buildings",
                "--no-buildings-tiles",
            ]
        )
        == 0
    )
    assert not (out / "layers" / "tiles").exists()
    index = out / "layers" / "city_buildings.usdc"
    if not index.is_file():
        index = out / "layers" / "city_buildings.usda"
    stage = Usd.Stage.Open(str(index))
    root = stage.GetPrimAtPath("/World/City/Buildings")
    assert not root.HasAuthoredPayloads()
    assert root.GetCustomData().get("buildings_tiles") is False
    meshes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh) and "Looks" not in str(p.GetPath())]
    assert any(p.GetName() == "LOD0" for p in meshes)
