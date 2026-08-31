from __future__ import annotations

import math
import re
from typing import Any

from shapely.geometry import LineString, Polygon, box
from shapely.ops import substring
from shapely.strtree import STRtree

from cityusd.geom import repair_polygon
from cityusd.osm_parse import OsmWay

_HEIGHT_RE = re.compile(r"^\s*([\d.]+)\s*(?:m|meters?)?\s*$", re.IGNORECASE)

LOD_LEVELS = [
    {"name": "LOD0", "cell_size_m": 200.0, "switch_distance_m": 0.0, "merge_materials": False},
    {"name": "LOD1", "cell_size_m": 800.0, "switch_distance_m": 1500.0, "merge_materials": False},
    {"name": "LOD2", "cell_size_m": 3200.0, "switch_distance_m": 6000.0, "merge_materials": True},
]


FLOOR_HEIGHT_M = 3.0
DEFAULT_FLOORS = 3
BUILDING_INSET_M = 0.06
MIN_FOOTPRINT_AREA_M2 = 4.0
CARRIAGEWAY_SEG_M = 80.0
ENCLOSED_COVER_RATIO = 0.85


def building_floors(tags: dict[str, str]) -> int:
    """Storeys from building:levels, else round(height/3), else 3."""
    raw_levels = tags.get("building:levels")
    if raw_levels:
        try:
            return max(1, int(round(float(str(raw_levels).strip()))))
        except ValueError:
            pass
    raw_height = tags.get("height")
    if raw_height:
        match = _HEIGHT_RE.match(raw_height.strip())
        if match:
            return max(1, int(round(float(match.group(1)) / FLOOR_HEIGHT_M)))
    return DEFAULT_FLOORS


def building_height_m(tags: dict[str, str]) -> float:
    """Height is always floors × 3.0 m so facade UV matches storeys."""
    return float(building_floors(tags)) * FLOOR_HEIGHT_M


def _geom_parts(obj) -> list:
    if obj is None:
        return []
    if isinstance(obj, (list, tuple)):
        return [g for g in obj if g is not None and not getattr(g, "is_empty", True)]
    if getattr(obj, "is_empty", True):
        return []
    return [obj]


def _query_hits(geom, parts: list, tree=None) -> list[int]:
    if not parts:
        return []
    if tree is None:
        if len(parts) == 1:
            try:
                return [0] if geom.intersects(parts[0]) else []
            except Exception:
                return [0]
        tree = STRtree(parts)
    hits = tree.query(geom)
    out: list[int] = []
    for raw in hits:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return out


def _append_line_segments(line, half: float, lines: list, half_widths: list[float]) -> None:
    length = float(line.length)
    if length <= CARRIAGEWAY_SEG_M:
        lines.append(line)
        half_widths.append(half)
        return
    start = 0.0
    while start < length - 1e-6:
        end = min(start + CARRIAGEWAY_SEG_M, length)
        seg = substring(line, start, end)
        if seg is not None and not getattr(seg, "is_empty", True) and seg.length > 1e-6:
            lines.append(seg)
            half_widths.append(half)
        if end >= length:
            break
        start = end


def carriageway_index(ways: list) -> tuple[list, list[float], object | None]:
    """Short motor-road segments + half-widths. No pavement polygons."""
    from cityusd.roads import is_motor_highway, way_width_m

    lines: list = []
    half_widths: list[float] = []
    for way in ways or []:
        if not is_motor_highway(getattr(way, "tags", None) or {}):
            continue
        coords = getattr(way, "coords_m", None)
        if coords is None or len(coords) < 2:
            continue
        line = LineString(coords)
        if line.is_empty or line.length <= 0:
            continue
        _append_line_segments(line, float(way_width_m(way.tags)) * 0.5, lines, half_widths)
    tree = STRtree(lines) if lines else None
    max_half = 0.0
    for w in half_widths:
        if w > max_half:
            max_half = w
    return lines, half_widths, tree, max_half


def _hits_carriageway(
    footprint, lines: list, half_widths: list[float], tree=None, max_half: float | None = None
) -> bool:
    if not lines:
        return False
    pad = float(max_half) if max_half is not None else 0.0
    if max_half is None:
        for w in half_widths:
            if w > pad:
                pad = w
    minx, miny, maxx, maxy = footprint.bounds
    query = box(minx - pad, miny - pad, maxx + pad, maxy + pad)
    for idx in _query_hits(query, lines, tree):
        try:
            if float(footprint.distance(lines[idx])) < half_widths[idx] - 1e-6:
                return True
        except Exception:
            continue
    return False


def _hits_road_polygons(footprint, roads: list, tree=None) -> bool:
    if not roads:
        return False
    for idx in _query_hits(footprint, roads, tree):
        try:
            if footprint.intersects(roads[idx]):
                return True
        except Exception:
            continue
    return False


def footprint_after_roads(
    way: OsmWay,
    roads_union,
    road_core=None,
    road_tree=None,
    core_tree=None,
    half_widths=None,
    max_half: float | None = None,
) -> object | None:
    """Keep a closed footprint, or drop it if it intersects a carriageway. No clip."""
    if not way.closed or len(way.coords_m) < 3:
        return None

    coords = list(way.coords_m)
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    footprint = Polygon(coords)
    if footprint.is_empty:
        return None
    if not footprint.is_valid:
        footprint = repair_polygon(footprint)
        if footprint is None or footprint.is_empty:
            return None

    if half_widths is not None:
        if _hits_carriageway(footprint, roads_union, half_widths, road_tree, max_half):
            return None
    else:
        roads = _geom_parts(roads_union)
        if _hits_road_polygons(footprint, roads, road_tree):
            return None

    try:
        inset = footprint.buffer(-BUILDING_INSET_M)
    except Exception:
        inset = None
    if inset is not None and not getattr(inset, "is_empty", True):
        footprint = inset
    if footprint is None or getattr(footprint, "is_empty", True):
        return None
    if float(getattr(footprint, "area", 0.0) or 0.0) < MIN_FOOTPRINT_AREA_M2:
        return None
    return footprint


def drop_enclosed_buildings(items: list) -> list:
    """Keep the outer footprint; drop buildings covered or mostly overlapping a larger one."""
    if len(items) < 2:
        return items
    geoms = [it.get("footprint") for it in items]
    tree = STRtree(geoms)
    areas = []
    for g in geoms:
        try:
            areas.append(float(g.area) if g is not None and not g.is_empty else 0.0)
        except Exception:
            areas.append(0.0)
    keep = [a > 0.0 for a in areas]
    for i, g in enumerate(geoms):
        if not keep[i]:
            continue
        for j in _query_hits(g, geoms, tree):
            if i == j or not keep[j]:
                continue
            other = geoms[j]
            try:
                if areas[j] < areas[i] - 1e-6:
                    continue
                covered = False
                if other.covers(g):
                    covered = True
                else:
                    inter = g.intersection(other)
                    inter_a = float(getattr(inter, "area", 0.0) or 0.0)
                    covered = inter_a / areas[i] >= ENCLOSED_COVER_RATIO
                if not covered:
                    continue
                if areas[j] > areas[i] + 1e-6:
                    keep[i] = False
                    break
                if abs(areas[j] - areas[i]) <= 1e-6 and j < i:
                    keep[i] = False
                    break
            except Exception:
                continue
    return [it for it, ok in zip(items, keep) if ok]


def lod_cell_key(x_m: float, y_m: float, cell_m: float) -> tuple[int, int]:
    return (math.floor(x_m / cell_m), math.floor(y_m / cell_m))


def group_buildings_for_lod(items: list, cell_m: float) -> dict[tuple[int, int], list]:
    """Group by footprint centroid."""
    groups: dict[tuple[int, int], list[Any]] = {}
    for item in items:
        footprint = item.get("footprint") if isinstance(item, dict) else getattr(item, "footprint", None)
        if footprint is None or footprint.is_empty:
            continue
        centroid = footprint.centroid
        key = lod_cell_key(centroid.x, centroid.y, cell_m)
        groups.setdefault(key, []).append(item)
    return groups
