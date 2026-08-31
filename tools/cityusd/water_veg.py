from __future__ import annotations

from typing import Optional

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from cityusd.geom import repair_polygon
from cityusd.osm_parse import OsmData, OsmWay

WATERWAY_WIDTH_M = {
    "river": 8.0,
    "stream": 3.0,
    "canal": 5.0,
    "default": 4.0,
}

skip_count = 0
_MAX_LOCAL_CUTTERS = 80

_VEG_LANDUSE = frozenset({"grass", "forest", "meadow"})
_WATERWAY_KINDS = frozenset({"river", "stream", "canal"})


def water_polygons(data: OsmData, cutters) -> list:
    """Closed water areas + buffered waterways; difference against roads+buildings."""
    out: list = []
    if data is None or not data.ways:
        return out
    index = prepare_cutters(cutters)
    for way in data.ways:
        geom = _water_geom(way)
        if geom is None:
            continue
        cut = _cut_or_skip(geom, index)
        if cut is None:
            continue
        out.extend(_as_polygon_list(cut))
    return out


def vegetation_polygons(data: OsmData, cutters) -> list:
    """Vegetation areas difference against roads+buildings."""
    out: list = []
    if data is None or not data.ways:
        return out
    index = prepare_cutters(cutters)
    for way in data.ways:
        if not _is_vegetation(way.tags):
            continue
        geom = _closed_polygon(way)
        if geom is None:
            continue
        cut = _cut_or_skip(geom, index)
        if cut is None:
            continue
        out.extend(_as_polygon_list(cut))
    return out


def _is_water_area(tags: dict[str, str]) -> bool:
    if tags.get("natural") == "water":
        return True
    if "water" in tags:
        return True
    if tags.get("landuse") == "reservoir":
        return True
    return False


def _is_waterway_line(tags: dict[str, str]) -> bool:
    return tags.get("waterway") in _WATERWAY_KINDS


def _is_vegetation(tags: dict[str, str]) -> bool:
    if tags.get("landuse") in _VEG_LANDUSE:
        return True
    if tags.get("leisure") == "park":
        return True
    if tags.get("natural") == "wood":
        return True
    return False


def _waterway_width_m(tags: dict[str, str]) -> float:
    kind = tags.get("waterway", "")
    return WATERWAY_WIDTH_M.get(kind, WATERWAY_WIDTH_M["default"])


def _water_geom(way: OsmWay) -> Optional[BaseGeometry]:
    if _is_water_area(way.tags):
        return _closed_polygon(way)
    if _is_waterway_line(way.tags):
        if way.coords_m is None or len(way.coords_m) < 2:
            return None
        line = LineString(way.coords_m)
        if line.is_empty or line.length == 0:
            return None
        width = _waterway_width_m(way.tags)
        if width <= 0:
            return None
        poly = line.buffer(width / 2.0)
        if poly is None or poly.is_empty:
            return None
        return poly
    return None


def _closed_polygon(way: OsmWay) -> Optional[BaseGeometry]:
    if not way.closed or way.coords_m is None or len(way.coords_m) < 3:
        return None
    coords = list(way.coords_m)
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    poly = Polygon(coords)
    if poly.is_empty:
        return None
    if not poly.is_valid:
        poly = repair_polygon(poly)
        if poly is None or poly.is_empty:
            return None
        if getattr(poly, "geom_type", "") not in ("Polygon", "MultiPolygon"):
            return None
    return poly


def prepare_cutters(cutters):
    """STRtree over a list of cutter polygons, or pass through a single geometry."""
    if cutters is None:
        return None
    if isinstance(cutters, (list, tuple)):
        geoms = [g for g in cutters if g is not None and not getattr(g, "is_empty", True)]
        if not geoms:
            return None
        return (STRtree(geoms), geoms)
    return cutters


def _cut_or_skip(geom: BaseGeometry, cutters) -> Optional[BaseGeometry]:
    """Difference against cutters; on failure skip and increment skip_count."""
    global skip_count
    if geom is None or geom.is_empty:
        return None
    if cutters is None:
        return geom
    if isinstance(cutters, tuple) and len(cutters) == 2 and isinstance(cutters[0], STRtree):
        tree, geoms = cutters
        hits = tree.query(geom, predicate="intersects")
        if len(hits) == 0:
            return geom
        if len(hits) > _MAX_LOCAL_CUTTERS:
            return geom
        parts = [geoms[int(i)] for i in hits]
        local = unary_union(parts) if len(parts) > 1 else parts[0]
        try:
            result = geom.difference(local)
        except Exception:
            skip_count += 1
            return None
        if result is None or result.is_empty:
            return None
        return result
    if getattr(cutters, "is_empty", False):
        return geom
    try:
        result = geom.difference(cutters)
    except Exception:
        skip_count += 1
        return None
    if result is None or result.is_empty:
        return None
    return result


def _as_polygon_list(geom: BaseGeometry) -> list:
    if geom is None or geom.is_empty:
        return []
    gtype = getattr(geom, "geom_type", "")
    if gtype == "Polygon":
        return [geom]
    if gtype == "MultiPolygon":
        return [g for g in geom.geoms if g is not None and not g.is_empty]
    if gtype == "GeometryCollection":
        out: list = []
        for g in geom.geoms:
            out.extend(_as_polygon_list(g))
        return out
    return []
