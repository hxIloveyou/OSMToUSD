from pathlib import Path
import json
from pxr import Usd, UsdGeom
from build_city_usd import main


def test_tiny_package(tmp_path):
    data = tmp_path / "data"
    (data / "osm").mkdir(parents=True)
    src = Path("tests/fixtures/tiny.osm")
    (data / "osm" / "tiny.osm").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out"
    rc = main(["--data", str(data), "--output", str(out), "--scene-id", "tiny_test"])
    assert rc == 0
    world = next(out.glob("World_*.usda"))
    stage = Usd.Stage.Open(str(world))
    assert stage.GetDefaultPrim().GetName() == "World"
    assert (out / "tiny_test-CostMap" / "2D" / "connected" / "map.pgm").exists()
    assert (out / "tiny_test-CostMap" / "2D" / "connected" / "map_local.yaml").exists()
    assert (out / "tiny_test-CostMap" / "2D" / "connected" / "map_soft.pgm").exists()
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["units"]["meters_per_unit"] == 0.01
    assert (out / "overlay" / "equipment.usda").exists()
    # no DEM → no heightmap file
    assert not (out / "terrain_src" / "heightmap_16bit.png").exists()
    city_layers = [
        out / "layers" / "city_roads.usdc",
        out / "layers" / "city_buildings.usdc",
        out / "layers" / "city_water.usdc",
        out / "layers" / "city_vegetation.usdc",
        out / "layers" / "city_lamps.usdc",
        out / "layers" / "city_signs.usdc",
    ]
    found = []
    for path in city_layers:
        alt = path.with_suffix(".usda")
        assert path.exists() or alt.exists()
        found.append(path if path.exists() else alt)
    roads = Usd.Stage.Open(str(found[0]))
    road_meshes = [
        p
        for p in roads.Traverse()
        if p.IsA(UsdGeom.Mesh) and "Looks" not in str(p.GetPath()) and "Arrows" not in str(p.GetPath())
    ]
    assert road_meshes
    mesh = UsdGeom.Mesh(road_meshes[0])
    assert UsdGeom.PrimvarsAPI(mesh).GetPrimvar("st").HasValue()
    assert (out / "textures" / "roads" / "asphalt.png").exists()
    assert (out / "textures" / "buildings" / "facade_low.png").exists()
    lamp_stage = Usd.Stage.Open(str(out / "models" / "prototypes" / "lamp.usda"))
    assert lamp_stage.GetPrimAtPath("/LampPlaceholder/Head").IsValid()
    assert lamp_stage.GetPrimAtPath("/LampPlaceholder/Glass").IsValid()
    assert lamp_stage.GetPrimAtPath("/LampPlaceholder/Arm").IsValid()
    bld_path = out / "layers" / "city_buildings.usdc"
    if not bld_path.exists():
        bld_path = out / "layers" / "city_buildings.usda"
    bld = Usd.Stage.Open(str(bld_path))
    bldg_meshes = [
        p for p in bld.Traverse() if p.IsA(UsdGeom.Mesh) and "Looks" not in str(p.GetPath())
    ]
    assert bldg_meshes
    names = {p.GetName() for p in bldg_meshes}
    assert "LOD0" in names
    assert "LOD1" not in names and "LOD2" not in names
    assert UsdGeom.Mesh(bldg_meshes[0]).GetDoubleSidedAttr().Get() is True
    signs_path = out / "layers" / "city_signs.usdc"
    if not signs_path.exists():
        signs_path = out / "layers" / "city_signs.usda"
    signs = Usd.Stage.Open(str(signs_path))
    sign_inst = [p for p in signs.Traverse() if p.GetName().startswith("I_Signs")]
    assert sign_inst
    lamps_path = out / "layers" / "city_lamps.usdc"
    if not lamps_path.exists():
        lamps_path = out / "layers" / "city_lamps.usda"
    assert lamps_path.exists()
    assert (out / "textures" / "furniture" / "arrow_decal.png").exists()


def test_missing_osm_exits(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    out = tmp_path / "out"
    rc = main(["--data", str(data), "--output", str(out)])
    assert rc != 0
    assert not out.exists()


def test_layer_set_selects_one_city_layer():
    from build_city_usd import _layer_set

    only_roads = _layer_set("roads")
    assert only_roads == {"roads"}
    assert "buildings" not in only_roads
    assert "buildings" in _layer_set("all")
    assert "lamps" in _layer_set("signs,lamps")
    assert "signs" in _layer_set("signs,lamps")
    assert "furniture" not in _layer_set("signs,lamps")
    assert {"lamps", "signs"} <= _layer_set("furniture")
    assert {"lamps", "signs"} <= _layer_set("all")
