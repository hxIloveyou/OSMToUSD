import json

import numpy as np
from shapely.geometry import box

from cityusd.crs import make_origin
from cityusd.pgm import FREE, OCCUPIED, COST_FREE, COST_LETHAL, occupancy_to_cost, rasterize_pgm
from cityusd.types import ExtentM


def _load_pgm(path):
    raw = path.read_bytes()
    assert raw.startswith(b"P5")
    # parse header
    i = 2
    while raw[i] in b" \t\r\n":
        i += 1
    parts = []
    while len(parts) < 3:
        if raw[i] == ord("#"):
            while raw[i] not in b"\r\n":
                i += 1
            i += 1
            continue
        start = i
        while raw[i] not in b" \t\r\n":
            i += 1
        parts.append(int(raw[start:i]))
        while raw[i] in b" \t\r\n":
            i += 1
    w, h, _ = parts
    return np.frombuffer(raw[i : i + w * h], dtype=np.uint8).reshape((h, w))


def test_building_is_occupied(tmp_path):
    extent = ExtentM(-50, -50, 50, 50)
    occ = [box(-10, -10, 10, 10)]
    free = [box(-40, -2, 40, 2)]
    o = make_origin(119.0, 36.0)
    rasterize_pgm(
        extent,
        occ,
        free,
        1.0,
        tmp_path / "map.pgm",
        tmp_path / "map.yaml",
        tmp_path / "map_meta.json",
        o,
        "osm_bbox",
    )
    raw = (tmp_path / "map.pgm").read_bytes()
    assert b"P5" in raw[:8]
    yaml_text = (tmp_path / "map.yaml").read_text(encoding="utf-8")
    assert "origin: [-50.0, -50.0, 0.0]" in yaml_text or "origin: [-50, -50, 0]" in yaml_text
    assert (tmp_path / "cost.pgm").is_file()
    meta = json.loads((tmp_path / "map_meta.json").read_text(encoding="utf-8"))
    assert meta["cost_values"]["lethal"] == 254
    assert meta["coverage_m"]["west"] == -50.0

    occ = np.array([[205, 254], [0, 205]], dtype=np.uint8)
    costg = occupancy_to_cost(occ)
    assert costg[0, 1] == COST_FREE
    assert costg[1, 0] == COST_LETHAL


def test_free_road_wins_over_building_overlap(tmp_path):
    """Motor free is painted after occupied so carriageways stay navigable."""
    extent = ExtentM(-50, -50, 50, 50)
    # Building square overlaps an E-W road strip
    occ = [box(-10, -10, 10, 10)]
    free = [box(-40, -2, 40, 2)]
    o = make_origin(119.0, 36.0)
    rasterize_pgm(
        extent,
        occ,
        free,
        1.0,
        tmp_path / "map.pgm",
        tmp_path / "map.yaml",
        tmp_path / "map_meta.json",
        o,
        "osm_bbox",
    )
    grid = _load_pgm(tmp_path / "map.pgm")
    # row 0 = north; y=+2 is near north of strip. Center (0,0):
    # col = x - west = 0 - (-50) = 50
    # row from north: north=50, y=0 → row = (50-0)/1 = 50... wait
    # coverage north = south + ny*res; extent -50..50 → ny=100, north=50
    # y_m = north - (row+0.5)*res ≈ for cell center
    # For pixel covering (0,0): col=(0-(-50))/1=50, row=(50-0)/1=50 if using top-left of cell
    # from_origin(west, north, res, res): row increases southward
    # pixel (row,col) center roughly at west+(col+0.5), north-(row+0.5)
    # For (0,0): col≈49.5→49 or 50, row≈49.5
    cy, cx = 50, 50  # approx map center
    assert grid[cy, cx] == FREE
    # Building corner away from road: (0, 8) → col=50, row = (50-8)=42
    assert grid[42, 50] == OCCUPIED


def test_cost_same_as_map(tmp_path):
    extent = ExtentM(-50, -50, 50, 50)
    occ = [box(-10, -10, 10, 10)]
    free = [box(-40, -2, 40, 2)]
    o = make_origin(119.0, 36.0)
    rasterize_pgm(
        extent,
        occ,
        free,
        1.0,
        tmp_path / "map.pgm",
        tmp_path / "map_local.yaml",
        tmp_path / "map_meta.json",
        o,
        "connected_test",
        free_all_touched=True,
        binary_occupancy=True,
        cost_same_as_map=True,
    )
    assert (tmp_path / "map.pgm").read_bytes() == (tmp_path / "cost.pgm").read_bytes()


def test_write_nav2_yaml_bundle(tmp_path):
    from cityusd.pgm import write_nav2_yaml_bundle

    from cityusd.types import Origin

    extent = ExtentM(-100.0, -50.0, 100.0, 50.0)
    o = Origin(lon=121.532933, lat=25.047453, height_m=0.0, epsg=32651)
    payload = {
        "utm_abs_m": {"e0": 352005.156, "n0": 2771004.448},
        "origin_wgs84": {"latitude": 25.047453, "longitude": 121.532933},
    }
    write_nav2_yaml_bundle(
        tmp_path,
        extent=extent,
        extent_payload=payload,
        origin=o,
        resolution_m=1.0,
        scene_id="test_scene",
    )
    local = (tmp_path / "map_local.yaml").read_text(encoding="utf-8")
    utm = (tmp_path / "map.yaml").read_text(encoding="utf-8")
    val = (tmp_path / "valhalla_origin.yaml").read_text(encoding="utf-8")
    assert "origin: [-100.0, -50.0, 0.0]" in local
    assert "origin: [351905.156" in utm
    assert "valhalla_origin:" in val
    assert "utm_zone: 51" in val


def test_connected_binary_no_unknown(tmp_path):
    """Connected mode: all_touched + binary background leaves no unknown gaps."""
    extent = ExtentM(-50, -50, 50, 50)
    occ = [box(-10, -10, 10, 10)]
    free = [box(-40, -2, 40, 2), box(-2, -2, 2, 40)]
    o = make_origin(119.0, 36.0)
    from cityusd.pgm import UNKNOWN

    rasterize_pgm(
        extent,
        occ,
        free,
        1.0,
        tmp_path / "map2.pgm",
        tmp_path / "map2.yaml",
        tmp_path / "map2_meta.json",
        o,
        "connected_test",
        free_all_touched=True,
        binary_occupancy=True,
    )
    grid = _load_pgm(tmp_path / "map2.pgm")
    assert int((grid == UNKNOWN).sum()) == 0
    assert grid[50, 50] == FREE


def test_soft_edge_occupancy_ramps_at_boundary():
    from cityusd.pgm import soft_edge_occupancy

    grid = np.full((21, 21), OCCUPIED, dtype=np.uint8)
    grid[5:16, 5:16] = FREE
    soft = soft_edge_occupancy(grid, resolution_m=1.0, radius_m=2.0)
    assert soft[10, 10] == FREE
    assert soft[0, 0] == OCCUPIED
    # Just outside the free square (row 4) should be intermediate gray
    assert 0 < int(soft[4, 10]) < FREE
