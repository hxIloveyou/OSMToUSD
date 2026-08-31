from pathlib import Path

from cityusd.scan_inputs import scan_data_dir


def test_prefers_pbf(tmp_path: Path):
    (tmp_path / "osm").mkdir()
    (tmp_path / "osm" / "a.osm").write_text("<osm/>")
    (tmp_path / "osm" / "b.osm.pbf").write_bytes(b"pbf")
    found = scan_data_dir(tmp_path)
    assert found.osm.name == "b.osm.pbf"


def test_missing_osm(tmp_path: Path):
    found = scan_data_dir(tmp_path)
    assert found.osm is None


def test_osm_subdir_before_root(tmp_path: Path):
    (tmp_path / "root.osm").write_text("<osm/>")
    (tmp_path / "osm").mkdir()
    (tmp_path / "osm" / "nested.osm").write_text("<osm/>")
    found = scan_data_dir(tmp_path)
    assert found.osm.name == "nested.osm"


def test_dem_largest_in_dem_dir(tmp_path: Path):
    dem_dir = tmp_path / "dem"
    dem_dir.mkdir()
    small = dem_dir / "small.tif"
    large = dem_dir / "large.tif"
    small.write_bytes(b"x" * 100)
    large.write_bytes(b"x" * 1000)
    found = scan_data_dir(tmp_path)
    assert found.dem == large


def test_imagery_excludes_dem(tmp_path: Path):
    imagery_dir = tmp_path / "imagery"
    imagery_dir.mkdir()
    shared = tmp_path / "shared.tif"
    shared.write_bytes(b"x" * 5000)
    other = imagery_dir / "view.png"
    other.write_bytes(b"x" * 100)
    found = scan_data_dir(tmp_path)
    assert found.dem == shared
    assert found.imagery == other


def test_descriptions_json(tmp_path: Path):
    desc_dir = tmp_path / "descriptions"
    desc_dir.mkdir()
    a = desc_dir / "a.json"
    b = desc_dir / "b.json"
    a.write_text("{}")
    b.write_text("{}")
    found = scan_data_dir(tmp_path)
    assert found.descriptions == sorted([a, b])


def test_assets_dir(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    found = scan_data_dir(tmp_path)
    assert found.assets_dir == assets


def test_assets_missing(tmp_path: Path):
    found = scan_data_dir(tmp_path)
    assert found.assets_dir is None
