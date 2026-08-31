from cityusd.inbox_assets import INBOX_ASSETS, layout_parts, oga_low_rise_role, relative_file, validate_catalog
from cityusd.inbox_unique import oga_unique_sheet_role, wiki_license_ok


def test_inbox_catalog_unique_and_cc0():
    rows = validate_catalog()
    assert len(rows) >= 40
    ids = [a["id"] for a in rows]
    assert len(ids) == len(set(ids))
    east = [a for a in rows if a["bucket"] == "east_asia"]
    gen = [a for a in rows if a["bucket"] == "generic"]
    assert east and gen
    assert any(a["part"] == "facade" for a in east)
    assert any(a["part"] == "roof" for a in east)
    assert any("corrugated" in a["notes"].lower() or "浪板" in a["notes"] for a in east)
    assert any("tile" in a["notes"].lower() for a in east)
    low = [a for a in rows if a["bucket"] == "low_rise"]
    assert any(a.get("role") == "shop" for a in low)
    assert any(a.get("role") == "residential" for a in low)


def test_inbox_paths_stay_under_inbox():
    allowed = ("/facades/", "/roofs/", "/signage/", "/details/")
    for a in INBOX_ASSETS:
        rel = relative_file(a)
        assert rel.startswith("materials/buildings/inbox/")
        assert any(part in rel for part in allowed)
        assert rel.endswith("_Color.jpg")
        assert ".." not in rel


def test_layout_puts_shop_roof_and_tower_in_browse_folders():
    shop = next(a for a in INBOX_ASSETS if a["id"] == "ph_rusty_metal_shutter")
    assert layout_parts(shop)[0] == "details"
    roof = next(a for a in INBOX_ASSETS if a["id"] == "acg_CorrugatedSteel009")
    assert layout_parts(roof) == ("roofs", "metal")
    tower = next(a for a in INBOX_ASSETS if a["id"] == "acg_Facade001")
    assert layout_parts(tower)[:2] == ("facades", "tileable")
    clay = next(a for a in INBOX_ASSETS if a["id"] == "acg_RoofingTiles001")
    assert layout_parts(clay) == ("roofs", "tile")


def test_oga_low_rise_keeps_shop_and_apartments():
    assert oga_low_rise_role("shop_front3.png") == "shop"
    assert oga_low_rise_role("shutters_door.png") == "shop"
    assert oga_low_rise_role("apartments5.png") == "residential"
    assert oga_low_rise_role("building_house1.png") == "residential"
    assert oga_low_rise_role("building_h_windows.png") == "residential"
    assert oga_low_rise_role("building_office3.png") is None
    assert oga_low_rise_role("building_church_side1.png") is None


def test_oga_unique_sheets_keep_offices_not_churches():
    assert oga_unique_sheet_role("building_office3.png") == "office"
    assert oga_unique_sheet_role("building_factory.png") == "industrial"
    assert oga_unique_sheet_role("shop_front3.png") is None
    assert oga_unique_sheet_role("building_church_side1.png") is None


def test_wiki_license_skips_sharealike():
    ok, lic = wiki_license_ok("CC0")
    assert ok and lic == "CC0"
    ok, _ = wiki_license_ok("CC BY 4.0")
    assert ok
    ok, _ = wiki_license_ok("CC BY-SA 4.0")
    assert not ok
