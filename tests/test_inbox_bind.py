from pathlib import Path

import pytest
from PIL import Image
from shapely.geometry import box

from cityusd.inbox_bind import (
    bind_inbox_photos,
    is_shop_building,
    uv_mode_for_path,
)
from cityusd.looks import facade_material_path, facade_variant
from cityusd.proc_textures import ensure_scene_textures


def _write_rgb(path: Path, rgb: tuple[int, int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), rgb).save(path)
    return path


def _fake_library(root: Path) -> Path:
    inbox = root / "materials" / "buildings" / "inbox"
    _write_rgb(inbox / "facades" / "sheets" / "shopfront" / "shop_a.jpg", (200, 40, 40))
    _write_rgb(inbox / "facades" / "sheets" / "residential" / "house_a.jpg", (40, 180, 40))
    _write_rgb(inbox / "facades" / "tileable" / "highrise" / "glass_a.jpg", (40, 40, 200))
    _write_rgb(inbox / "facades" / "sheets" / "office" / "office_a.jpg", (180, 180, 40))
    _write_rgb(inbox / "roofs" / "tile" / "tile_a.jpg", (140, 60, 40))
    return root


def test_shop_tags_use_shopfront_variants():
    assert is_shop_building({"building": "retail"})
    assert is_shop_building({"shop": "convenience"})
    assert is_shop_building({"amenity": "restaurant"})
    assert not is_shop_building({"building": "apartments"})
    assert facade_variant(1, "low", {"building": "retail"}) < 8
    assert facade_variant(1, "low", {"building": "yes"}) >= 8
    assert "Facade_low_" in facade_material_path("low", 1, {"shop": "yes"})


def test_sheet_paths_are_unique_uv():
    assert uv_mode_for_path(Path("inbox/facades/sheets/residential/a.jpg")) == "unique_sheet"
    assert uv_mode_for_path(Path("inbox/facades/tileable/highrise/a.jpg")) == "unique_sheet"
    assert uv_mode_for_path(Path("inbox/facades/tileable/cladding/a.jpg")) == "tile"


def test_bind_inbox_splits_low_shop_and_house(tmp_path):
    lib = _fake_library(tmp_path / "AssetLibrary")
    photos, roofs, modes = bind_inbox_photos(lib)
    assert len(photos["low"]) == 16
    assert modes["low"][:8] == ["unique_sheet"] * 8
    assert all(p.name.startswith("shop_") for p in photos["low"][:8])
    assert all(p.name.startswith("house_") for p in photos["low"][8:])
    assert photos["tower"]
    assert roofs
    assert modes["tower"][0] == "unique_sheet"


def test_bind_missing_inbox_is_empty(tmp_path):
    photos, roofs, modes = bind_inbox_photos(tmp_path / "missing")
    assert photos == {}
    assert roofs == []
    assert modes == {}


def test_inbox_photos_keep_sheet_uv(tmp_path):
    lib = _fake_library(tmp_path / "AssetLibrary")
    photos, roofs, modes = bind_inbox_photos(lib)
    written = ensure_scene_textures(
        tmp_path / "textures",
        facade_photos=photos,
        roof_photos=roofs,
        facade_uv_modes=modes,
    )
    assert written["_facade_uv"]["facade_low_0"] == "unique_sheet"
    assert written["_facade_uv"]["facade_low_8"] == "unique_sheet"
    assert written["_facade_uv"]["facade_tower_0"] == "unique_sheet"
    from PIL import Image as PilImage

    low0 = PilImage.open(written["facade_low_0"])
    assert low0.size[0] >= 1024
    roof = PilImage.open(written["roof_0"]).convert("RGB")
    sample = roof.getpixel((4, 4))
    assert sum(sample) / 3.0 < 110
    assert max(sample) - min(sample) < 24


def test_unique_sheet_uv_matches_storey_module():
    from build_city_usd import _extrude_one

    mesh = _extrude_one(
        box(0.0, 0.0, 12.0, 8.0), 9.0, 0.0, tile_floors=3, uv_mode="unique_sheet", sheet_width_m=12.0
    )
    pts, _counts, _indices, uvs, walls, _roofs = mesh
    n_roof = len(pts) - 4 * len(walls)
    # First wall of shapely box is 8 m / 12 m sheet.
    assert uvs[n_roof + 1][0] == pytest.approx(8.0 / 12.0)
    # 9 m tall / 3 storeys × 3 m.
    assert uvs[n_roof + 2][1] == pytest.approx(1.0)
    tiled = _extrude_one(box(0.0, 0.0, 12.0, 8.0), 9.0, 0.0, tile_floors=3, uv_mode="tile")
    t_uvs = tiled[3]
    t_walls = tiled[4]
    t_roof = len(tiled[0]) - 4 * len(t_walls)
    assert t_uvs[t_roof][0] == 0.0
    assert t_uvs[t_roof + 1][0] == pytest.approx(800.0 / (600.0 * 12.0))


def test_collinear_footprint_nodes_merge_to_four_walls():
    from shapely.geometry import Polygon
    from build_city_usd import _extrude_one

    poly = Polygon([(0.0, 0.0), (6.0, 0.0), (12.0, 0.0), (12.0, 8.0), (0.0, 8.0), (0.0, 0.0)])
    mesh = _extrude_one(poly, 9.0, 0.0, tile_floors=3, uv_mode="unique_sheet")
    assert len(mesh[4]) == 4
