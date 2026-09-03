import json
from pathlib import Path

from pxr import Usd, UsdGeom

from cityusd.furniture import placeholder_tree_mesh
from cityusd.package import (
    WORLD_SUBLAYERS,
    build_package_meta,
    write_empty_overlay,
    write_meta,
    write_prototype_files,
    write_world,
)
from cityusd.usd_write import (
    write_environment_layer,
    write_mesh,
    write_nav_layer,
    write_placeholder_prototype,
    write_point_instancer,
    write_terrain_layer,
)


def test_world_opens(tmp_path):
    env = tmp_path / "layers" / "environment.usda"
    env.parent.mkdir(parents=True)
    write_environment_layer(env)
    ov = tmp_path / "overlay"
    ov.mkdir()
    write_empty_overlay(ov / "equipment.usda", "Equipment")
    world = tmp_path / "World_test.usda"
    write_world(world, "test", [
        "./layers/environment.usda",
        "./overlay/equipment.usda",
    ])
    stage = Usd.Stage.Open(str(world))
    assert stage.GetDefaultPrim().GetName() == "World"
    assert UsdGeom.GetStageMetersPerUnit(stage) == 0.01
    for name in ("Roads", "Buildings", "Water", "Vegetation", "Lamps", "Signs"):
        assert stage.GetPrimAtPath(f"/World/City/{name}").IsValid()


def test_world_up_axis_and_sublayers(tmp_path):
    world = tmp_path / "World_sub.usda"
    write_world(world, "sub", list(WORLD_SUBLAYERS))
    stage = Usd.Stage.Open(str(world))
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
    assert list(stage.GetRootLayer().subLayerPaths) == list(WORLD_SUBLAYERS)


def test_overlay_empty_xforms(tmp_path):
    names = [
        "Equipment",
        "Infrastructure",
        "ObstaclesStatic",
        "ObstaclesDynamic",
        "Props",
    ]
    for name in names:
        path = tmp_path / f"{name}.usda"
        write_empty_overlay(path, name)
        stage = Usd.Stage.Open(str(path))
        prim = stage.GetPrimAtPath(f"/World/Overlay/{name}")
        assert prim.IsValid()
        assert prim.IsA(UsdGeom.Xform)
        assert list(prim.GetChildren()) == []
        assert UsdGeom.GetStageMetersPerUnit(stage) == 0.01
        assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z


def test_terrain_nav_custom_data(tmp_path):
    terrain = tmp_path / "terrain.usda"
    write_terrain_layer(
        terrain,
        "./terrain_src/heightmap_16bit.png",
        "./terrain_src/ortho.png",
        None,
    )
    tstage = Usd.Stage.Open(str(terrain))
    tprim = tstage.GetPrimAtPath("/World/Terrain")
    tcd = tprim.GetCustomData()
    assert tcd["heightmap_png"] == "./terrain_src/heightmap_16bit.png"
    assert tcd["ortho_png"] == "./terrain_src/ortho.png"
    assert tcd["alignment_json"] == "./terrain_src/alignment.json"
    plane = tstage.GetPrimAtPath("/World/Terrain/RefPlane")
    assert plane.IsValid()
    assert UsdGeom.Imageable(plane).GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible

    nav = tmp_path / "nav.usda"
    write_nav_layer(
        nav,
        "../CostMap/2D/connected/map.pgm",
        "../CostMap/2D/connected/map_local.yaml",
        "../CostMap/2D/connected/cost.pgm",
    )
    nstage = Usd.Stage.Open(str(nav))
    ncd = nstage.GetPrimAtPath("/World/Nav").GetCustomData()
    assert ncd["map_pgm"] == "../CostMap/2D/connected/map.pgm"
    assert ncd["map_yaml"] == "../CostMap/2D/connected/map_local.yaml"
    assert ncd["cost_pgm"] == "../CostMap/2D/connected/cost.pgm"
    assert ncd["alignment_json"] == "./terrain_src/alignment.json"


def test_point_instancer_and_prototype(tmp_path):
    path = tmp_path / "veg.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    verts, faces = placeholder_tree_mesh()
    proto = "/World/City/Vegetation/Prototypes/TreePlaceholder"
    write_placeholder_prototype(stage, proto, verts, faces)
    write_point_instancer(
        stage,
        "/World/City/Vegetation/I_Trees",
        proto,
        [(100.0, 200.0, 0.0), (300.0, 0.0, 0.0)],
        [0.0, 1.57],
    )
    write_mesh(
        stage,
        "/World/City/Buildings/c0_0/LOD0",
        [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 100.0, 0.0)],
        [3],
        [0, 1, 2],
        None,
    )
    stage.GetRootLayer().Save()

    opened = Usd.Stage.Open(str(path))
    inst = UsdGeom.PointInstancer(opened.GetPrimAtPath("/World/City/Vegetation/I_Trees"))
    positions = list(inst.GetPositionsAttr().Get())
    assert len(positions) == 2
    assert abs(positions[0][0] - 100.0) < 1e-4
    targets = [str(t) for t in inst.GetPrototypesRel().GetTargets()]
    assert any("TreePlaceholder" in t for t in targets)
    assert opened.GetPrimAtPath("/World/City/Buildings/c0_0/LOD0").IsA(UsdGeom.Mesh)


def test_prototype_files_and_meta(tmp_path):
    tree, lamp, sign = write_prototype_files(tmp_path / "models")
    assert tree.name == "tree.usda"
    assert lamp.name == "lamp.usda"
    assert sign.name == "sign.usda"
    tstage = Usd.Stage.Open(str(tree))
    lstage = Usd.Stage.Open(str(lamp))
    sstage = Usd.Stage.Open(str(sign))
    assert tstage.GetDefaultPrim() is not None
    assert lstage.GetDefaultPrim() is not None
    head = UsdGeom.Mesh(lstage.GetPrimAtPath("/LampPlaceholder/Head"))
    colors = head.GetDisplayColorAttr().Get()
    assert colors and float(colors[0][0]) > 0.8
    board = UsdGeom.Mesh(sstage.GetPrimAtPath("/SignPlaceholder/Board"))
    assert board.GetPrim().IsValid()
    assert board.GetDoubleSidedAttr().Get() is False
    crown = UsdGeom.Mesh(tstage.GetPrimAtPath("/TreePlaceholder/Crown"))
    assert float(crown.GetDisplayColorAttr().Get()[0][1]) > 0.3

    payload = build_package_meta("demo", crs={"epsg": 32651})
    meta_path = tmp_path / "meta.json"
    write_meta(meta_path, payload)
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["spec_version"] == "1.0"
    assert data["scene_id"] == "demo"
    assert data["crs"]["epsg"] == 32651
    assert data["units"]["meters_per_unit"] == 0.01
    assert data["vegetation_instancer"] is True
    assert data["lamp_instancer"] is True
    assert data["prototype_swap"] is True
    assert data["capabilities"]["has_building_lod"] is True
    assert "lod" in data
    assert "layers" in data
    assert "overlay" in data


def test_backup_zips_previous_usd(tmp_path):
    from cityusd.package import backup_existing_usd

    out = tmp_path / "ScenePackage"
    (out / "layers").mkdir(parents=True)
    target = out / "layers" / "city_buildings.usdc"
    target.write_bytes(b"fake-usdc")
    (out / "layers" / "city_roads.usdc").write_bytes(b"roads")
    zipped = backup_existing_usd(out, {"buildings"}, "taibei")
    assert zipped is not None and zipped.exists()
    assert zipped.parent.name == "backups"
    import zipfile

    with zipfile.ZipFile(zipped) as zf:
        names = zf.namelist()
    assert "layers/city_buildings.usdc" in names
    assert "layers/city_roads.usdc" not in names
    assert target.read_bytes() == b"fake-usdc"


def test_backup_skips_when_nothing_to_save(tmp_path):
    from cityusd.package import backup_existing_usd

    out = tmp_path / "ScenePackage"
    out.mkdir()
    assert backup_existing_usd(out, {"buildings"}, "taibei") is None
