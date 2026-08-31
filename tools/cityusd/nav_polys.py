"""Collect occupied/free polygons for Nav2 PGM (OSM-only v0.2)."""

from __future__ import annotations

from shapely.geometry import Polygon

from cityusd.buildings import (
    carriageway_index,
    drop_enclosed_buildings,
    footprint_after_roads,
)
from cityusd.geom import repair_polygon
from cityusd.osm_parse import OsmData, OsmWay
from cityusd.roads import (
    build_road_polygons,
    is_motor_highway,
    motor_carriageway_polygons,
    subtract_road_hierarchy,
)
from cityusd.water_veg import water_polygons


def _iter_polygons(geom):
    if geom is None or getattr(geom, "is_empty", True):
        return
    gt = getattr(geom, "geom_type", None)
    if gt == "Polygon":
        yield geom
    elif gt == "MultiPolygon":
        for p in geom.geoms:
            if not p.is_empty:
                yield p


def flatten_polys(geoms) -> list:
    out = []
    for g in geoms or []:
        out.extend(_iter_polygons(g))
    return out


def _building_footprints(osm: OsmData) -> list:
    highway_ways = [w for w in osm.ways if w.tags.get("highway")]
    road_lines, road_half, road_tree, road_pad = carriageway_index(highway_ways)
    items = []
    for way in osm.ways:
        if "building" not in way.tags:
            continue
        try:
            fp = footprint_after_roads(
                way,
                road_lines,
                road_tree=road_tree,
                half_widths=road_half,
                max_half=road_pad,
            )
        except Exception:
            continue
        if fp is None or getattr(fp, "is_empty", True):
            continue
        items.append({"footprint": fp})
    items = drop_enclosed_buildings(items)
    return [it["footprint"] for it in items]


def _simple_building_footprints(osm: OsmData) -> list:
    out = []
    for way in osm.ways:
        if "building" not in way.tags or not way.closed or len(way.coords_m) < 3:
            continue
        try:
            g = repair_polygon(Polygon(way.coords_m))
            if g is not None and not g.is_empty:
                out.append(g)
        except Exception:
            continue
    return out


def collect_nav_polygons(
    osm: OsmData,
    *,
    use_buildings: bool = True,
    use_water: bool = True,
    use_roads_free: bool = True,
    simple_buildings: bool = False,
) -> tuple[list, list]:
    occupied: list = []
    free: list = []

    if use_buildings:
        if simple_buildings:
            occupied.extend(_simple_building_footprints(osm))
        else:
            occupied.extend(_building_footprints(osm))

    if use_water:
        occupied.extend(water_polygons(osm, None))

    if use_roads_free:
        highway_ways = [w for w in osm.ways if w.tags.get("highway")]
        if highway_ways:
            buffered = build_road_polygons(highway_ways)
            ranked = subtract_road_hierarchy(buffered)
            free = [
                g
                for w, g in ranked
                if g is not None and not getattr(g, "is_empty", True) and is_motor_highway(w.tags)
            ]
        if not free:
            free = motor_carriageway_polygons(osm.ways)

    return flatten_polys(occupied), flatten_polys(free)
