import math

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from cityusd.osm_parse import OsmWay
from cityusd.roads import (
    arrow_decal_quad_cm,
    build_road_polygons,
    build_typed_junctions,
    clip_marking_to_road,
    classify_junction_kind,
    effective_lane_count,
    graph_degree_from_ways,
    inbound_lane_offsets_m,
    is_motor_highway,
    junction_arrows,
    lane_separator_offsets_m,
    marking_kind,
    marking_strip_polygons,
    sign_placements,
    split_line_coords_at_junctions,
    subtract_road_hierarchy,
    way_display_name,
    way_elevation_m,
    way_width_m,
)


def test_width_lanes_override():
    assert way_width_m({"highway": "residential", "lanes": "2"}) == 7.0


def test_primary_double_yellow():
    k = marking_kind({"highway": "primary"}, 12.0)
    assert k["center"] == "double_yellow_solid"


def test_footway_not_motor():
    assert is_motor_highway({"highway": "footway"}) is False


def test_motorway_cuts_residential():
    motor = OsmWay(
        osm_id=1,
        tags={"highway": "motorway"},
        coords_m=[(0.0, 0.0), (100.0, 0.0)],
        closed=False,
    )
    res = OsmWay(
        osm_id=2,
        tags={"highway": "residential"},
        coords_m=[(50.0, -50.0), (50.0, 50.0)],
        closed=False,
    )
    buffered = build_road_polygons([motor, res])
    orig = {w.osm_id: g.area for w, g in buffered}
    ranked = subtract_road_hierarchy(buffered)
    cut = {w.osm_id: g.area for w, g in ranked if w.osm_id}
    assert cut[1] <= orig[1]
    assert cut[2] < orig[2]
    geoms = [g for w, g in ranked if w.osm_id and g is not None and not g.is_empty]
    if len(geoms) >= 2:
        inter = geoms[0].intersection(geoms[1])
        assert getattr(inter, "area", 0.0) < 0.5


def test_lower_rank_markings_stay_off_higher_road():
    motor = OsmWay(1, {"highway": "motorway"}, [(0.0, 0.0), (100.0, 0.0)], False)
    res = OsmWay(2, {"highway": "residential"}, [(50.0, -50.0), (50.0, 50.0)], False)
    ranked = subtract_road_hierarchy(build_road_polygons([motor, res]))
    geom_by = {w.osm_id: g for w, g in ranked if g is not None and not g.is_empty}
    kept = []
    for strip in marking_strip_polygons(res.coords_m, res.tags, way_width_m(res.tags)):
        clipped = clip_marking_to_road(strip["geom"], geom_by[2])
        if clipped is not None and not getattr(clipped, "is_empty", True):
            kept.append(clipped)
    assert kept
    unioned = unary_union(kept)
    assert not unioned.covers(Point(50.0, 0.0))
    assert unioned.distance(Point(50.0, 25.0)) < 2.0
    motor_kept = []
    for strip in marking_strip_polygons(motor.coords_m, motor.tags, way_width_m(motor.tags)):
        clipped = clip_marking_to_road(strip["geom"], geom_by[1])
        if clipped is not None and not getattr(clipped, "is_empty", True):
            motor_kept.append(clipped)
    motor_union = unary_union(motor_kept)
    assert motor_union.distance(Point(50.0, 0.0)) < 0.5


def test_same_rank_overlap_replaced_by_junction():
    a = OsmWay(10, {"highway": "residential"}, [(0.0, 0.0), (80.0, 0.0)], False)
    b = OsmWay(11, {"highway": "residential"}, [(40.0, -40.0), (40.0, 40.0)], False)
    ranked = subtract_road_hierarchy(build_road_polygons([a, b]))
    roads = [g for w, g in ranked if g is not None and not getattr(g, "is_empty", True)]
    assert len(roads) >= 2
    assert roads[0].intersection(roads[1]).area < 0.5


def test_buffer_uses_flat_caps_not_round():
    way = OsmWay(1, {"highway": "residential"}, [(0.0, 0.0), (40.0, 0.0)], False)
    poly = build_road_polygons([way])[0][1]
    assert poly.covers(Point(39.0, 0.0))
    assert not poly.covers(Point(42.0, 0.0))


def test_collinear_ways_meet_without_cap_gap():
    a = OsmWay(1, {"highway": "residential"}, [(0.0, 0.0), (50.0, 0.0)], False)
    b = OsmWay(2, {"highway": "residential"}, [(50.0, 0.0), (100.0, 0.0)], False)
    ranked = subtract_road_hierarchy(build_road_polygons([a, b]))
    geoms = [g for _w, g in ranked if g is not None and not getattr(g, "is_empty", True)]
    assert len(geoms) == 1
    assert geoms[0].covers(Point(50.0, 0.0))
    if geoms[0].geom_type == "Polygon":
        assert len(geoms[0].interiors) == 0


def test_short_kink_is_still_arced():
    a = OsmWay(1, {"highway": "residential"}, [(0.0, 0.0), (8.0, 0.0)], False)
    b = OsmWay(2, {"highway": "residential"}, [(8.0, 0.0), (8.0, 8.0)], False)
    buffered = build_road_polygons([a, b])
    assert len(buffered) == 1
    line = LineString(buffered[0][0].coords_m)
    assert line.distance(Point(8.0, 0.0)) > 0.15
    assert len(buffered[0][0].coords_m) >= 8


def test_degree2_kink_is_rounded():
    a = OsmWay(1, {"highway": "residential"}, [(0.0, 0.0), (40.0, 0.0)], False)
    b = OsmWay(2, {"highway": "residential"}, [(40.0, 0.0), (40.0, 40.0)], False)
    buffered = build_road_polygons([a, b])
    assert len(buffered) == 1
    line = LineString(buffered[0][0].coords_m)
    assert line.distance(Point(40.0, 0.0)) > 0.4
    assert len(buffered[0][0].coords_m) >= 8


def test_t_junction_stays_separate_ways():
    a = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (50.0, 0.0)], False)
    b = OsmWay(2, {"highway": "primary"}, [(50.0, 0.0), (100.0, 0.0)], False)
    side = OsmWay(3, {"highway": "primary"}, [(50.0, 0.0), (50.0, 40.0)], False)
    assert len(build_road_polygons([a, b, side])) == 2


def test_named_bend_merges_past_side_road():
    a = OsmWay(1, {"highway": "primary", "name": "中山路"}, [(0.0, 0.0), (40.0, 0.0)], False)
    b = OsmWay(2, {"highway": "primary", "name": "中山路"}, [(40.0, 0.0), (40.0, 40.0)], False)
    side = OsmWay(3, {"highway": "residential"}, [(40.0, 0.0), (80.0, 0.0)], False)
    buffered = build_road_polygons([a, b, side])
    assert len(buffered) == 2
    main = [w for w, _g in buffered if w.tags.get("name") == "中山路"]
    assert main
    assert LineString(main[0].coords_m).distance(Point(40.0, 0.0)) > 0.2


def test_unnamed_bend_merges_past_lower_side():
    a = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (40.0, 0.0)], False)
    b = OsmWay(2, {"highway": "primary"}, [(40.0, 0.0), (40.0, 40.0)], False)
    side = OsmWay(3, {"highway": "residential"}, [(40.0, 0.0), (80.0, 0.0)], False)
    buffered = build_road_polygons([a, b, side])
    assert len(buffered) == 2
    mains = [w for w, _g in buffered if w.tags.get("highway") == "primary"]
    assert len(mains) == 1
    assert LineString(mains[0].coords_m).distance(Point(40.0, 0.0)) > 0.2
    assert len(mains[0].coords_m) >= 16


def test_bent_through_markings_stay_continuous():
    a = OsmWay(1, {"highway": "primary", "name": "中山路"}, [(0.0, 0.0), (40.0, 0.0)], False)
    b = OsmWay(2, {"highway": "primary", "name": "中山路"}, [(40.0, 0.0), (40.0, 40.0)], False)
    side = OsmWay(3, {"highway": "residential"}, [(40.0, 0.0), (80.0, 0.0)], False)
    buffered = build_road_polygons([a, b, side])
    main = [w for w, _g in buffered if w.tags.get("name") == "中山路"][0]
    deg = graph_degree_from_ways([a, b, side])
    pts = [Point(float(k[0]), float(k[1])) for k, d in deg.items() if int(d) >= 3]
    pieces = split_line_coords_at_junctions(main.coords_m, pts, setback_m=5.0)
    assert len(pieces) == 1
    assert LineString(pieces[0]).length > 50.0


def test_width_change_is_tapered():
    narrow = OsmWay(1, {"highway": "primary", "lanes": "2"}, [(0.0, 0.0), (40.0, 0.0)], False)
    wide = OsmWay(2, {"highway": "primary", "lanes": "4"}, [(40.0, 0.0), (80.0, 0.0)], False)
    buffered = build_road_polygons([narrow, wide])
    assert len(buffered) == 1
    poly = buffered[0][1]

    def width_at(x: float) -> float:
        hit = poly.intersection(LineString([(x, -40.0), (x, 40.0)]))
        return float(getattr(hit, "length", 0.0))

    assert abs(width_at(10.0) - 7.0) < 1.5
    assert abs(width_at(70.0) - 14.0) < 2.0
    mid = width_at(40.0)
    assert 8.0 < mid < 13.0
    # Transition should not be a knife-edge: nearby samples stay close
    assert abs(width_at(36.0) - width_at(44.0)) < 5.0


def test_marking_lane_count_uses_typical_not_narrowest_spike():
    coords = [(0.0, 0.0), (40.0, 0.0), (80.0, 0.0), (120.0, 0.0)]
    # Mostly 14 m with one narrow spike — should still keep 4-lane separators
    vary = [14.0, 14.0, 7.0, 14.0]
    strips = marking_strip_polygons(
        coords, {"highway": "primary", "lanes": "4"}, 14.0, vertex_width_m=vary
    )
    assert [s for s in strips if s["style"] == "white_dash"]


def test_short_piece_skips_unstable_edge_offsets():
    # Tiny stub: should not emit spaghetti edge markings
    strips = marking_strip_polygons(
        [(0.0, 0.0), (2.0, 0.0)], {"highway": "primary", "lanes": "4"}, 14.0
    )
    assert strips == []


def test_stable_offset_does_not_explode_on_sharp_bend():
    coords = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0)]
    strips = marking_strip_polygons(coords, {"highway": "primary", "lanes": "4"}, 14.0)
    edges = [s for s in strips if s["style"] == "white_solid"]
    assert edges
    for s in edges:
        # Each dash/solid fragment should stay compact relative to its bounds
        minx, miny, maxx, maxy = s["geom"].bounds
        assert (maxx - minx) < 40.0 and (maxy - miny) < 40.0


def test_through_node_is_junction_degree():
    through = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False)
    side = OsmWay(2, {"highway": "primary"}, [(50.0, 0.0), (50.0, 40.0)], False)
    deg = graph_degree_from_ways([through, side])
    assert deg[(50.0, 0.0)] >= 3
    # Two-way major junction → topology arrows (not empty)
    twoway = junction_arrows(build_road_polygons([through, side]), deg)
    assert twoway
    assert all("kind" in a for a in twoway)

    through_ow = OsmWay(
        1, {"highway": "primary", "oneway": "yes"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False
    )
    side_ow = OsmWay(2, {"highway": "primary", "oneway": "yes"}, [(50.0, 40.0), (50.0, 0.0)], False)
    arrows = junction_arrows(build_road_polygons([through_ow, side_ow]), deg)
    assert arrows
    assert max(len(a["poly"].exterior.coords) for a in arrows) >= 6
    line_ys = [abs(a["xy"][1]) for a in arrows if abs(a["xy"][1]) < 3.0]
    assert line_ys
    assert all(abs(y - 3.0) > 0.4 for y in line_ys)
    assert all(1.0 < y < 2.2 for y in line_ys)


def test_inbound_offsets_sit_between_lane_lines():
    offsets = inbound_lane_offsets_m({"highway": "primary"}, 12.0)
    assert offsets == [1.5]
    assert all(abs(o - 3.0) > 0.5 for o in offsets)
    pts, counts, indices, uvs = arrow_decal_quad_cm()
    assert counts == [4]
    assert len(pts) == 4
    # tip='up' default: tip edge has v=1
    assert max(uv[1] for uv in uvs) == 1.0
    pts_r, _, _, uvs_r = arrow_decal_quad_cm(tip="right")
    assert max(uv[0] for uv in uvs_r) == 1.0
    assert pts_r == pts


def test_way_display_name_prefers_zh():
    assert way_display_name({"name:zh": "中山北路", "name": "Zhongshan N Rd"}) == "中山北路"
    assert way_display_name({"name:zh-Hans": "中山路", "name:zh-Hant": "中山路"}) == "中山路"
    assert way_display_name({"name:zh-Hant": "復興南路"}) == "复兴南路"
    assert way_display_name({"highway": "residential"}) == ""


def test_dashed_lane_is_geometric_segments():
    strips = marking_strip_polygons([(0.0, 0.0), (50.0, 0.0)], {"highway": "primary"}, 12.0)
    dashes = [s for s in strips if s["style"] == "white_dash"]
    solids = [s for s in strips if s["style"] == "white_solid"]
    assert len(dashes) >= 6
    assert solids
    dash_len = max(s["geom"].bounds[2] - s["geom"].bounds[0] for s in dashes)
    assert dash_len < 6.0


def test_effective_lane_count_caps_by_width():
    # Tagged 4 lanes but only ~7 m pavement → 2 lanes
    assert effective_lane_count({"highway": "primary", "lanes": "4"}, 7.0) == 2
    assert effective_lane_count({"highway": "primary", "lanes": "4"}, 14.0) == 4
    # Width alone (~12 m primary default) → ~3–4; prefer even for two-way
    assert effective_lane_count({"highway": "primary"}, 12.0) in {2, 3, 4}
    assert effective_lane_count({"highway": "primary", "lanes": "2"}, 14.0) == 2


def test_two_lane_primary_has_no_lane_dashes():
    offsets = lane_separator_offsets_m({"highway": "primary", "lanes": "2"}, 7.0)
    assert offsets == []
    strips = marking_strip_polygons(
        [(0.0, 0.0), (40.0, 0.0)], {"highway": "primary", "lanes": "2"}, 7.0
    )
    assert [s for s in strips if s["style"] == "white_dash"] == []
    assert any("yellow" in s["style"] for s in strips)


def test_four_lane_separators_at_quarter_width():
    w = 14.0
    offsets = lane_separator_offsets_m({"highway": "primary", "lanes": "4"}, w)
    assert sorted(offsets) == sorted([-w / 4.0, w / 4.0])


def test_six_lane_has_two_separators_each_side():
    w = 21.0
    offsets = lane_separator_offsets_m({"highway": "primary", "lanes": "6"}, w)
    assert sorted(offsets) == sorted([-w / 6.0, w / 6.0, -2.0 * w / 6.0, 2.0 * w / 6.0])


def test_narrow_tagged_four_lane_markings_follow_width():
    # Same tags as a 4-lane road, but drawn at 7 m → behave like 2-lane
    strips = marking_strip_polygons(
        [(0.0, 0.0), (40.0, 0.0)], {"highway": "primary", "lanes": "4"}, 7.0
    )
    assert [s for s in strips if s["style"] == "white_dash"] == []


def test_variable_width_uses_narrowest_for_lane_count():
    # Entire piece is narrow → drop to 2-lane (no white separators)
    coords = [(0.0, 0.0), (40.0, 0.0), (80.0, 0.0)]
    vary = [7.0, 7.0, 7.0]
    strips = marking_strip_polygons(
        coords, {"highway": "primary", "lanes": "4"}, 14.0, vertex_width_m=vary
    )
    assert [s for s in strips if s["style"] == "white_dash"] == []


def test_inbound_offset_matches_first_lane_center():
    # 4 lanes @ 14 m → first inbound bay center at w/(2n) = 1.75
    assert inbound_lane_offsets_m({"highway": "primary", "lanes": "4"}, 14.0) == [1.75]
    assert inbound_lane_offsets_m({"highway": "primary", "lanes": "2"}, 7.0) == [1.75]


def test_oneway_has_no_double_yellow():
    k = marking_kind({"highway": "primary", "oneway": "yes"}, 14.0)
    assert k["center"] == "none"
    assert k["lane"] == "white_dash"


def test_oneway_even_lanes_center_sep_not_over_yellow():
    # Even oneway: one separator sits at 0; must not stack with yellow center
    tags = {"highway": "primary", "oneway": "yes", "lanes": "4"}
    w = 14.0
    assert 0.0 in lane_separator_offsets_m(tags, w)
    strips = marking_strip_polygons([(0.0, 0.0), (40.0, 0.0)], tags, w)
    yellow = [s for s in strips if "yellow" in s["style"]]
    assert yellow == []
    dashes = [s for s in strips if s["style"] == "white_dash"]
    assert dashes  # mid-carriageway separators still present


def test_two_way_yellow_not_coincident_with_lane_dash():
    tags = {"highway": "primary", "lanes": "4"}
    w = 14.0
    strips = marking_strip_polygons([(0.0, 0.0), (50.0, 0.0)], tags, w)
    # Sample mid-road cross section: yellow near y=0, dashes near ±w/4
    yellow_ys = []
    dash_ys = []
    for s in strips:
        b = s["geom"].bounds
        cy = 0.5 * (b[1] + b[3])
        if "yellow" in s["style"]:
            yellow_ys.append(cy)
        if s["style"] == "white_dash":
            dash_ys.append(cy)
    assert yellow_ys and dash_ys
    for y in yellow_ys:
        assert all(abs(y - d) > 0.35 for d in dash_ys)


def test_classify_junction_kinds():
    assert classify_junction_kind([0.0, math.pi, math.pi / 2.0]) == "tee"
    assert classify_junction_kind([0.0, math.pi / 2.0, math.pi, -math.pi / 2.0]) == "cross"
    assert classify_junction_kind([0.0, 2.0 * math.pi / 3.0, 4.0 * math.pi / 3.0]) == "wye"


def test_all_roads_stay_on_ground():
    assert way_elevation_m({"highway": "primary"}) == 0.0
    assert way_elevation_m({"highway": "primary", "layer": "2"}) == 0.0
    assert way_elevation_m({"highway": "primary", "bridge": "yes"}) == 0.0
    assert way_elevation_m({"highway": "primary", "bridge": "yes", "layer": "2"}) == 0.0
    assert way_elevation_m({"highway": "primary", "tunnel": "yes"}) == 0.0


def test_tee_junction_matches_stem_crosswalk():
    through = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False)
    side = OsmWay(2, {"highway": "primary"}, [(50.0, 0.0), (50.0, 40.0)], False)
    ways = [through, side]
    juncs = build_typed_junctions(ways, graph_degree_from_ways(ways), build_road_polygons(ways))
    tees = [j for j in juncs if j["kind"] == "tee"]
    assert tees
    patch = tees[0]["geom"]
    assert patch.covers(Point(50.0, 0.0))
    assert not patch.covers(Point(50.0, -7.2))
    assert tees[0]["zebra"]
    assert all(z.centroid.y > 1.0 for z in tees[0]["zebra"])
    z0 = tees[0]["zebra"][0]
    minx, miny, maxx, maxy = z0.bounds
    assert (maxy - miny) > (maxx - minx)


def test_cross_clip_stays_local():
    h = OsmWay(1, {"highway": "primary"}, [(0.0, 40.0), (40.0, 40.0), (80.0, 40.0)], False)
    v = OsmWay(2, {"highway": "primary"}, [(40.0, 0.0), (40.0, 40.0), (40.0, 80.0)], False)
    ways = [h, v]
    deg = graph_degree_from_ways(ways)
    juncs = build_typed_junctions(ways, deg, build_road_polygons(ways))
    crosses = [j for j in juncs if j["kind"] == "cross"]
    assert crosses
    patch = crosses[0]["geom"]
    assert patch.covers(Point(40.0, 40.0))
    assert not patch.covers(Point(65.0, 40.0))
    assert not patch.covers(Point(52.0, 52.0))
    assert crosses[0]["zebra"]
    assert len(crosses[0]["zebra"]) >= 12


def test_wye_and_roundabout_kinds():
    a = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (30.0, 0.0)], False)
    b = OsmWay(
        2,
        {"highway": "primary"},
        [(0.0, 0.0), (30.0 * math.cos(2.0 * math.pi / 3.0), 30.0 * math.sin(2.0 * math.pi / 3.0))],
        False,
    )
    c = OsmWay(
        3,
        {"highway": "primary"},
        [(0.0, 0.0), (30.0 * math.cos(4.0 * math.pi / 3.0), 30.0 * math.sin(4.0 * math.pi / 3.0))],
        False,
    )
    wyes = [j for j in build_typed_junctions([a, b, c], graph_degree_from_ways([a, b, c])) if j["kind"] == "wye"]
    assert wyes
    assert wyes[0]["geom"].covers(Point(0.0, 0.0))
    assert wyes[0]["zebra"]

    ring = [(12.0 * math.cos(i * math.pi / 8.0), 12.0 * math.sin(i * math.pi / 8.0)) for i in range(16)]
    ring.append(ring[0])
    ra = OsmWay(9, {"highway": "primary", "junction": "roundabout"}, ring, True)
    rjs = build_typed_junctions([ra], graph_degree_from_ways([ra]))
    assert rjs and rjs[0]["kind"] == "roundabout"
    geom = rjs[0]["geom"]
    assert geom.covers(Point(12.0, 0.0))
    assert not geom.covers(Point(0.0, 0.0))


def test_non_primary_junction_uses_disk_not_typed():
    through = OsmWay(1, {"highway": "residential"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False)
    side = OsmWay(2, {"highway": "residential"}, [(50.0, 0.0), (50.0, 40.0)], False)
    juncs = build_typed_junctions([through, side], graph_degree_from_ways([through, side]))
    assert all(j["kind"] not in {"tee", "cross", "wye"} for j in juncs)
    mixed_side = OsmWay(3, {"highway": "residential"}, [(50.0, 0.0), (50.0, 40.0)], False)
    mixed_through = OsmWay(4, {"highway": "primary"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False)
    mixed = build_typed_junctions(
        [mixed_through, mixed_side],
        graph_degree_from_ways([mixed_through, mixed_side]),
    )
    assert all(j["kind"] not in {"tee", "cross", "wye"} for j in mixed)


def test_dual_carriageway_cross_is_one_junction():
    left = OsmWay(1, {"highway": "primary"}, [(0.0, -40.0), (0.0, 0.0), (0.0, 10.0), (0.0, 50.0)], False)
    right = OsmWay(2, {"highway": "primary"}, [(10.0, -40.0), (10.0, 0.0), (10.0, 10.0), (10.0, 50.0)], False)
    south = OsmWay(3, {"highway": "primary"}, [(-40.0, 0.0), (0.0, 0.0), (10.0, 0.0), (50.0, 0.0)], False)
    north = OsmWay(4, {"highway": "primary"}, [(-40.0, 10.0), (0.0, 10.0), (10.0, 10.0), (50.0, 10.0)], False)
    ways = [left, right, south, north]
    juncs = [j for j in build_typed_junctions(ways, graph_degree_from_ways(ways), build_road_polygons(ways)) if j["kind"] != "disk"]
    assert len(juncs) == 1
    j = juncs[0]
    assert j["kind"] == "cross"
    assert j["geom"].covers(Point(5.0, 5.0))
    assert j["geom"].covers(Point(0.0, 0.0))
    assert j["geom"].covers(Point(10.0, 10.0))
    assert not j["geom"].covers(Point(5.0, 40.0))
    zebra_n = len(j["zebra"])
    assert 12 <= zebra_n <= 24


def test_coplanar_bridge_tag_is_deduped():
    ground = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (80.0, 0.0)], False)
    bridge = OsmWay(
        2,
        {"highway": "primary", "bridge": "yes", "layer": "1"},
        [(40.0, -40.0), (40.0, 40.0)],
        False,
    )
    ranked = subtract_road_hierarchy(build_road_polygons([ground, bridge]))
    geoms = {w.osm_id: g for w, g in ranked if g is not None and not g.is_empty}
    assert geoms[1].intersection(geoms[2]).area < 0.5
    assert geoms[1].area > 700.0
    assert geoms[2].area > 700.0


def test_sign_placements_skip_unnamed():
    named = OsmWay(1, {"highway": "primary", "name": "测试路"}, [(0.0, 0.0), (80.0, 0.0)], False)
    unnamed = OsmWay(2, {"highway": "primary"}, [(0.0, 10.0), (80.0, 10.0)], False)
    placed = sign_placements([named, unnamed])
    assert placed
    assert all(p["name"] == "测试路" for p in placed)


def test_skip_osm_junction_area_mesh():
    junc = OsmWay(
        1,
        {"highway": "junction"},
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (0.0, 0.0)],
        True,
    )
    road = OsmWay(2, {"highway": "primary"}, [(0.0, 10.0), (40.0, 10.0)], False)
    buffered = build_road_polygons([junc, road])
    assert all(w.osm_id != 1 for w, _g in buffered)
    assert any(w.osm_id == 2 for w, _g in buffered)


def test_markings_stop_before_t_node():
    through = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False)
    side = OsmWay(2, {"highway": "primary"}, [(50.0, 0.0), (50.0, 40.0)], False)
    deg = graph_degree_from_ways([through, side])
    pts = [Point(float(k[0]), float(k[1])) for k, d in deg.items() if int(d) >= 3]
    pieces = split_line_coords_at_junctions(through.coords_m, pts, setback_m=5.0)
    assert pieces
    node = Point(50.0, 0.0)
    for piece in pieces:
        assert LineString(piece).distance(node) > 4.0
    stem = split_line_coords_at_junctions(side.coords_m, pts, setback_m=5.0)
    assert stem
    for piece in stem:
        assert LineString(piece).distance(node) > 4.0


def test_cross_arrows_do_not_stack():
    ns = OsmWay(
        1, {"highway": "primary", "oneway": "yes"}, [(0.0, -80.0), (0.0, 0.0), (0.0, 80.0)], False
    )
    ew = OsmWay(
        2, {"highway": "primary", "oneway": "yes"}, [(-80.0, 0.0), (0.0, 0.0), (80.0, 0.0)], False
    )
    arrows = junction_arrows(build_road_polygons([ns, ew]), graph_degree_from_ways([ns, ew]))
    # oneway only → one inbound per arm (not decorative 4-way)
    assert len(arrows) >= 2
    for i, a in enumerate(arrows):
        for b in arrows[i + 1 :]:
            dx = a["xy"][0] - b["xy"][0]
            dy = a["xy"][1] - b["xy"][1]
            dist = math.hypot(dx, dy)
            yaw_gap = abs(math.atan2(math.sin(a["yaw_rad"] - b["yaw_rad"]), math.cos(a["yaw_rad"] - b["yaw_rad"])))
            if 0.6 < yaw_gap < math.pi - 0.6:
                assert dist > 4.0


def test_closed_roundabout_has_no_ring_arrows():
    ring = [(18.0 * math.cos(i * math.pi / 8.0), 18.0 * math.sin(i * math.pi / 8.0)) for i in range(16)]
    ring.append(ring[0])
    ra = OsmWay(1, {"highway": "primary", "junction": "roundabout"}, ring, True)
    arm = OsmWay(2, {"highway": "primary", "oneway": "yes"}, [(70.0, 0.0), (18.0, 0.0)], False)
    arrows = junction_arrows(build_road_polygons([ra, arm]), graph_degree_from_ways([ra, arm]))
    assert arrows
    for a in arrows:
        assert math.hypot(a["xy"][0], a["xy"][1]) > 20.0


def test_open_roundabout_arcs_have_no_ring_arrows():
    top = [(18.0 * math.cos(i * math.pi / 8.0), 18.0 * math.sin(i * math.pi / 8.0)) for i in range(0, 9)]
    bot = [(18.0 * math.cos(i * math.pi / 8.0), 18.0 * math.sin(i * math.pi / 8.0)) for i in range(8, 17)]
    ra_a = OsmWay(1, {"highway": "primary", "junction": "roundabout"}, top, False)
    ra_b = OsmWay(2, {"highway": "primary", "junction": "roundabout"}, bot, False)
    arm = OsmWay(3, {"highway": "primary", "oneway": "yes"}, [(70.0, 0.0), (18.0, 0.0)], False)
    arrows = junction_arrows(
        build_road_polygons([ra_a, ra_b, arm]),
        graph_degree_from_ways([ra_a, ra_b, arm]),
    )
    for a in arrows:
        assert math.hypot(a["xy"][0], a["xy"][1]) > 20.0


def test_untagged_loop_arc_has_no_ring_arrows():
    ring = [(18.0 * math.cos(i * math.pi / 8.0), 18.0 * math.sin(i * math.pi / 8.0)) for i in range(16)]
    ra = OsmWay(1, {"highway": "primary"}, ring, False)
    arm = OsmWay(2, {"highway": "primary", "oneway": "yes"}, [(70.0, 0.0), (18.0, 0.0)], False)
    arrows = junction_arrows(build_road_polygons([ra, arm]), graph_degree_from_ways([ra, arm]))
    for a in arrows:
        assert math.hypot(a["xy"][0], a["xy"][1]) > 20.0


def test_bidirectional_major_road_has_topology_arrows():
    through = OsmWay(1, {"highway": "primary"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False)
    side = OsmWay(2, {"highway": "primary"}, [(50.0, 0.0), (50.0, 40.0)], False)
    arrows = junction_arrows(build_road_polygons([through, side]), graph_degree_from_ways([through, side]))
    assert arrows
    kinds = {a.get("kind") for a in arrows}
    assert kinds & {"straight", "left", "right", "straight_left", "straight_right", "all", "left_right"}


def test_turn_lanes_parse_and_place():
    from cityusd.roads import parse_turn_lane_kinds

    kinds = parse_turn_lane_kinds({"turn:lanes": "left|through|through;right"}, "forward")
    assert kinds == ["left", "straight", "straight_right"]
    way = OsmWay(
        1,
        {"highway": "primary", "oneway": "yes", "lanes": "3", "turn:lanes": "left|through|right"},
        [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)],
        False,
    )
    side = OsmWay(2, {"highway": "primary", "oneway": "yes"}, [(50.0, 40.0), (50.0, 0.0)], False)
    arrows = junction_arrows(build_road_polygons([way, side]), graph_degree_from_ways([way, side]))
    through_arrows = [a for a in arrows if abs(a["xy"][1]) < 4.0]
    assert len(through_arrows) >= 3
    assert {a["kind"] for a in through_arrows} >= {"left", "straight", "right"}


def test_oneway_reverse_arrow_direction():
    # Travel westbound (oneway=-1 along eastward coords): inbound at (50,0) from the east
    through = OsmWay(
        1, {"highway": "primary", "oneway": "-1"}, [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], False
    )
    side = OsmWay(2, {"highway": "primary", "oneway": "yes"}, [(50.0, 40.0), (50.0, 0.0)], False)
    arrows = junction_arrows(build_road_polygons([through, side]), graph_degree_from_ways([through, side]))
    assert arrows
    through_arrows = [a for a in arrows if abs(a["xy"][1]) < 3.0]
    assert through_arrows
    # Inbound toward junction from +x → yaw near π
    assert any(abs(math.cos(a["yaw_rad"]) + 1.0) < 0.35 for a in through_arrows)
