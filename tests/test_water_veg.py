from pathlib import Path

from cityusd.osm_parse import parse_osm
from cityusd.water_veg import water_polygons

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tiny.osm"


def test_tiny_water_one_polygon():
    data = parse_osm(FIXTURE)
    polys = water_polygons(data, None)
    assert len(polys) == 1
