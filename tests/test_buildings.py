from shapely.geometry import LineString, Point, Polygon

from cityusd.buildings import (
    building_height_m,
    carriageway_index,
    drop_enclosed_buildings,
    footprint_after_roads,
    lod_cell_key,
)
from cityusd.osm_parse import OsmWay


def test_levels():
    assert building_height_m({"building": "yes", "building:levels": "3"}) == 9.0


def test_default_three_floors():
    assert building_height_m({"building": "yes"}) == 9.0


def test_height_snaps_to_floors():
    assert building_height_m({"building": "yes", "height": "10"}) == 9.0
    assert building_height_m({"building": "yes", "height": "18.4"}) == 18.0


def test_cell():
    assert lod_cell_key(250.0, 50.0, 200.0) == (1, 0)


def test_building_spanning_road_is_dropped():
    road = LineString([(0.0, 0.0), (40.0, 0.0)]).buffer(6.0)
    core = road.buffer(-1.5)
    spanning = OsmWay(
        1,
        {"building": "yes"},
        [(18.0, -8.0), (22.0, -8.0), (22.0, 8.0), (18.0, 8.0), (18.0, -8.0)],
        True,
    )
    assert footprint_after_roads(spanning, road, core) is None
    beside = OsmWay(
        2,
        {"building": "yes"},
        [(18.0, 8.0), (26.0, 8.0), (26.0, 14.0), (18.0, 14.0), (18.0, 8.0)],
        True,
    )
    kept = footprint_after_roads(beside, road, core)
    assert kept is not None and not kept.is_empty
    assert footprint_after_roads(spanning, [road], [core]) is None
    kept_list = footprint_after_roads(beside, [road], [core])
    assert kept_list is not None and not kept_list.is_empty


def test_building_nicking_road_is_dropped():
    road = LineString([(0.0, 0.0), (40.0, 0.0)]).buffer(6.0)
    nick = OsmWay(
        3,
        {"building": "yes"},
        [(10.0, 5.0), (18.0, 5.0), (18.0, 12.0), (10.0, 12.0), (10.0, 5.0)],
        True,
    )
    assert footprint_after_roads(nick, road) is None


def test_carriageway_index_drops_overlap_keeps_beside():
    road = OsmWay(10, {"highway": "primary"}, [(0.0, 0.0), (40.0, 0.0)], False)
    lines, half, tree, _pad = carriageway_index([road])
    spanning = OsmWay(
        1,
        {"building": "yes"},
        [(18.0, -8.0), (22.0, -8.0), (22.0, 8.0), (18.0, 8.0), (18.0, -8.0)],
        True,
    )
    beside = OsmWay(
        2,
        {"building": "yes"},
        [(18.0, 8.0), (26.0, 8.0), (26.0, 14.0), (18.0, 14.0), (18.0, 8.0)],
        True,
    )
    assert footprint_after_roads(spanning, lines, road_tree=tree, half_widths=half) is None
    kept = footprint_after_roads(beside, lines, road_tree=tree, half_widths=half)
    assert kept is not None and not kept.is_empty
    assert kept.covers(Point(22.0, 11.0))


def test_large_building_spanning_road_is_dropped():
    road = LineString([(0.0, 0.0), (200.0, 0.0)]).buffer(6.0)
    core = road.buffer(-1.5)
    spanning = OsmWay(
        4,
        {"building": "yes"},
        [(-10.0, -12.0), (170.0, -12.0), (170.0, 12.0), (-10.0, 12.0), (-10.0, -12.0)],
        True,
    )
    assert footprint_after_roads(spanning, road, core) is None


def test_building_mostly_covering_road_is_dropped():
    road = LineString([(0.0, 0.0), (100.0, 0.0)]).buffer(6.0)
    along = OsmWay(
        6,
        {"building": "yes"},
        [(5.0, -7.0), (95.0, -7.0), (95.0, 7.0), (5.0, 7.0), (5.0, -7.0)],
        True,
    )
    assert footprint_after_roads(along, road, None) is None


def test_enclosed_building_is_dropped():
    outer = {"footprint": Polygon([(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]), "way": OsmWay(1, {}, [], True)}
    inner = {"footprint": Polygon([(5.0, 5.0), (8.0, 5.0), (8.0, 8.0), (5.0, 8.0)]), "way": OsmWay(2, {}, [], True)}
    beside = {"footprint": Polygon([(22.0, 0.0), (28.0, 0.0), (28.0, 6.0), (22.0, 6.0)]), "way": OsmWay(3, {}, [], True)}
    kept = drop_enclosed_buildings([outer, inner, beside])
    ids = {it["way"].osm_id for it in kept}
    assert ids == {1, 3}


def test_duplicate_overlap_keeps_one():
    a = {"footprint": Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]), "way": OsmWay(1, {}, [], True)}
    b = {"footprint": Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]), "way": OsmWay(2, {}, [], True)}
    kept = drop_enclosed_buildings([a, b])
    assert len(kept) == 1
