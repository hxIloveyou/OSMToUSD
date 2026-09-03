from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade

from cityusd.looks import facade_band, facade_variant, road_texture_key
from cityusd.proc_textures import ensure_scene_textures
from cityusd.usd_write import configure_stage, write_building_cell, write_mesh, write_preview_material


def test_road_texture_key_by_highway():
    assert road_texture_key("motorway") == "highway"
    assert road_texture_key("primary") == "national"
    assert road_texture_key("residential") == "asphalt"
    assert road_texture_key("footway") == "path"
    assert road_texture_key("service") == "cement"


def test_facade_band_by_height():
    assert facade_band(8.0) == "low"
    assert facade_band(15.0) == "mid"
    assert facade_band(24.0) == "mid"
    assert facade_band(27.0) == "high"
    assert facade_band(36.0) == "high"
    assert facade_band(80.0) == "tower"


def test_low_shop_and_house_use_different_variant_slots():
    assert 0 <= facade_variant(9, "low", {"building": "commercial"}) < 8
    assert facade_variant(9, "low", {"building": "apartments"}) >= 8
    assert facade_variant(3, "tower") == 3 % 8


def test_scene_textures_written(tmp_path):
    written = ensure_scene_textures(tmp_path / "textures")
    for key in ("highway", "asphalt", "path", "facade_low", "roof", "sign_board", "lamp_head", "arrow_decal"):
        assert key in written
        assert written[key].is_file()
        assert written[key].stat().st_size > 100
    assert "facade_low_0" in written
    assert "roof_3" in written
    from PIL import Image

    roof_px = Image.open(written["roof_0"]).convert("RGB")
    sample = roof_px.getpixel((64, 64))
    mean = sum(sample) / 3.0
    chroma = max(sample) - min(sample)
    assert 35 < mean < 100
    assert chroma < 24
    from cityusd.proc_textures import write_sign_board_png

    named = tmp_path / "textures" / "sign_named.png"
    write_sign_board_png(named, text="中山路")
    assert named.is_file() and named.stat().st_size > 200
    from PIL import Image
    from cityusd.proc_textures import write_arrow_decal_png

    arrow = tmp_path / "textures" / "arrow_check.png"
    write_arrow_decal_png(arrow)
    px = Image.open(arrow).convert("RGBA").getpixel((400, 128))
    assert px[0] > 240 and px[1] > 240 and px[2] > 240 and px[3] > 200


def test_mesh_writes_uvs_and_textured_material(tmp_path):
    path = tmp_path / "mesh.usda"
    stage = configure_stage(path)
    tex = tmp_path / "asphalt.png"
    tex.write_bytes(b"")  # placeholder; writer only needs a path string
    from cityusd.proc_textures import write_solid_png

    write_solid_png(tex, (40, 40, 40))
    write_preview_material(stage, "/World/Looks/RoadAsphalt", texture_path="./asphalt.png")
    write_mesh(
        stage,
        "/World/City/Roads/r1",
        [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 100.0, 0.0), (0.0, 100.0, 0.0)],
        [4],
        [0, 1, 2, 3],
        "/World/Looks/RoadAsphalt",
        uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        display_color=(0.2, 0.2, 0.2),
    )
    stage.GetRootLayer().Save()

    opened = Usd.Stage.Open(str(path))
    mesh = UsdGeom.Mesh(opened.GetPrimAtPath("/World/City/Roads/r1"))
    st = UsdGeom.PrimvarsAPI(mesh).GetPrimvar("st")
    assert st and st.HasValue()
    assert len(st.Get()) == 4
    colors = mesh.GetDisplayColorAttr().Get()
    assert colors and colors[0][0] < 0.5
    mat = UsdShade.Material(opened.GetPrimAtPath("/World/Looks/RoadAsphalt"))
    assert mat.GetPrim().IsValid()
    shader = opened.GetPrimAtPath("/World/Looks/RoadAsphalt/DiffuseTex")
    assert shader.IsValid()


def test_building_cell_keeps_walls_and_roof_as_geomsubsets(tmp_path):
    path = tmp_path / "cell.usda"
    stage = configure_stage(path)
    write_preview_material(stage, "/World/Looks/Facade_mid_0", (0.72, 0.58, 0.42))
    write_preview_material(stage, "/World/Looks/Roof_0", (0.28, 0.29, 0.30))
    pts = [
        (0.0, 0.0, 0.0),
        (100.0, 0.0, 0.0),
        (100.0, 100.0, 0.0),
        (0.0, 100.0, 0.0),
        (0.0, 0.0, 50.0),
        (100.0, 0.0, 50.0),
        (100.0, 100.0, 50.0),
        (0.0, 100.0, 50.0),
    ]
    payload = (
        pts,
        [4, 4],
        [0, 1, 2, 3, 4, 5, 6, 7],
        [(0.0, 0.0)] * 8,
        "/World/Looks/Facade_mid_0",
        (0.72, 0.58, 0.42),
        {
            "Walls": ([0], "/World/Looks/Facade_mid_0"),
            "Roof": ([1], "/World/Looks/Roof_0"),
        },
    )
    write_building_cell(stage, 0, 0, {"LOD0": payload}, suffix="mid_0")
    stage.GetRootLayer().Save()
    opened = Usd.Stage.Open(str(path))
    mesh_prim = opened.GetPrimAtPath("/World/City/Buildings/c400_0_0_mid_0/LOD0")
    assert mesh_prim.IsValid() and mesh_prim.IsA(UsdGeom.Mesh)
    assert not opened.GetPrimAtPath("/World/City/Buildings/c400_0_0_mid_0/LOD0_Roof").IsValid()
    walls = opened.GetPrimAtPath("/World/City/Buildings/c400_0_0_mid_0/LOD0/Walls")
    roof = opened.GetPrimAtPath("/World/City/Buildings/c400_0_0_mid_0/LOD0/Roof")
    assert walls.IsValid() and walls.GetTypeName() == "GeomSubset"
    assert roof.IsValid() and roof.GetTypeName() == "GeomSubset"
    mesh = UsdGeom.Mesh(mesh_prim)
    assert len(mesh.GetFaceVertexCountsAttr().Get()) == 2
    assert mesh.GetDisplayColorAttr().Get()[0][0] > 0.6
    parent_cd = opened.GetPrimAtPath("/World/City/Buildings/c400_0_0_mid_0").GetCustomData()
    assert parent_cd.get("building_mesh_mode") == "closed_mesh_geomsubset"
