from __future__ import annotations

import math
import re
from typing import Iterable, Optional

from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import substring
from shapely.strtree import STRtree

from cityusd.geom import difference_safe
from cityusd.osm_parse import OsmWay
from cityusd.types import CM_PER_M, LAYER_Z_M

ROAD_WIDTH_M = {
    "motorway": 22.0,
    "trunk": 16.0,
    "primary": 12.0,
    "secondary": 9.0,
    "tertiary": 7.0,
    "residential": 6.0,
    "service": 4.0,
    "footway": 2.0,
    "path": 2.0,
    "default": 5.0,
}
ROAD_RANK = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "service",
    "footway",
    "path",
]

NON_MOTOR_HIGHWAYS = frozenset(
    {
        "footway",
        "path",
        "steps",
        "pedestrian",
        "cycleway",
        "bridleway",
        "corridor",
        "construction",
        "proposed",
        "raceway",
        "busway",
    }
)
_WIDTH_RE = re.compile(r"^\s*([\d.]+)\s*(?:m|meters?)?\s*$", re.IGNORECASE)

MARKING_BUFFER_M = 0.08
MARKING_Z_M = LAYER_Z_M["roads"] + 0.01
DOUBLE_YELLOW_SEP_M = 0.18
ARROW_LENGTH_M = 5.0
ARROW_WIDTH_M = 1.15
ARROW_SETBACK_M = 8.0
SIGN_LATERAL_EXTRA_M = 0.6
DASH_ON_M = 4.0
DASH_GAP_M = 6.0
_MIN_OVERLAP_AREA_M2 = 1e-6
JUNCTION_EXTRA_M = 1.8
JUNCTION_CLUSTER_M = 24.0
SKIP_HIGHWAY_MESH = frozenset({"junction", "rest_area", "services", "platform"})
STOP_LINE_M = 0.45
CROSSWALK_STRIPE_M = 0.40
CROSSWALK_GAP_M = 0.40
CROSSWALK_STRIPES = 5
_ARM_HEADING_TOL = 0.49  # ~28°
_OPPOSITE_TOL = 0.52  # ~30°
BRIDGE_DECK_M = 5.5


def arrow_decal_quad_cm():
    """Flat XY quad, tip toward +X. Texture UV: u=1 at the tip. No volume, no collision mesh."""
    half_l = ARROW_LENGTH_M * 0.5 * CM_PER_M
    half_w = ARROW_WIDTH_M * 0.5 * CM_PER_M
    pts = [
        (half_l, half_w, 0.0),
        (half_l, -half_w, 0.0),
        (-half_l, -half_w, 0.0),
        (-half_l, half_w, 0.0),
    ]
    uvs = [(1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0)]
    return pts, [4], [0, 1, 2, 3], uvs


def lane_count(tags: dict[str, str], width_m: Optional[float] = None) -> int:
    """Carriageway lane count from `lanes`, else inferred from width (~3.5 m). Two-way prefers even."""
    raw_lanes = tags.get("lanes")
    if raw_lanes is not None:
        parsed = _parse_float(str(raw_lanes).split(";")[0].split("|")[0])
        if parsed is not None:
            return max(1, int(round(parsed)))
    if width_m is None:
        width_m = way_width_m(tags)
    approx = max(2, int(round(float(width_m) / 3.5)))
    oneway = (tags.get("oneway") or "").strip().lower() in {"yes", "true", "1"}
    if oneway or approx % 2 == 0:
        return approx
    lo, hi = approx - 1, approx + 1
    lo = max(2, lo)
    err_lo = abs(float(width_m) / lo - 3.5)
    err_hi = abs(float(width_m) / hi - 3.5)
    return lo if err_lo <= err_hi else hi


def inbound_lane_offsets_m(tags: dict[str, str], width_m: float) -> list[float]:
    """First inbound lane center, using the same layout as painted markings.

    Lane dashes are drawn at ±width/4. The arrow belongs in the bay between the
    centerline and that dash (width/8), never on the dash (width/4).
    """
    w = float(width_m)
    kind = marking_kind(tags, w)
    if kind.get("lane") == "white_dash":
        return [0.125 * w]
    return [0.25 * w]


def way_width_m(tags: dict[str, str]) -> float:
    raw_width = tags.get("width")
    if raw_width is not None:
        match = _WIDTH_RE.match(str(raw_width).strip())
        if match:
            return float(match.group(1))
    raw_lanes = tags.get("lanes")
    if raw_lanes is not None:
        parsed = _parse_float(raw_lanes)
        if parsed is not None:
            return parsed * 3.5
    hwy = tags.get("highway", "")
    return ROAD_WIDTH_M.get(hwy, ROAD_WIDTH_M["default"])


def is_motor_highway(tags: dict[str, str]) -> bool:
    """True if highway set and not a non-motor / non-carriageway class."""
    hwy = tags.get("highway")
    if not hwy:
        return False
    return hwy not in NON_MOTOR_HIGHWAYS


def motor_carriageway_polygons(ways: list) -> list:
    """Simple half-width buffers of motor highways. No pavement hierarchy cut."""
    polys: list = []
    for way in ways or []:
        tags = getattr(way, "tags", None) or {}
        if not is_motor_highway(tags):
            continue
        coords = getattr(way, "coords_m", None)
        if coords is None or len(coords) < 2:
            continue
        line = LineString(coords)
        if line.is_empty or line.length <= 0:
            continue
        buf = line.buffer(float(way_width_m(tags)) * 0.5)
        if buf is None or buf.is_empty:
            continue
        polys.append(buf)
    return polys


def is_major_highway(tags: dict[str, str]) -> bool:
    """Trunk network used for signs/arrows so UE instance counts stay bounded."""
    return (tags.get("highway") or "") in {"motorway", "trunk", "primary", "secondary"}


PRIMARY_JUNCTION_HIGHWAYS = frozenset({"motorway", "trunk", "primary"})


def is_primary_junction_highway(tags: dict[str, str]) -> bool:
    """一级路：仅这些道路的交汇做 T / 十字 / Y / 环岛。"""
    return (tags.get("highway") or "") in PRIMARY_JUNCTION_HIGHWAYS


def _is_roundabout_way(way: OsmWay) -> bool:
    junc = (way.tags.get("junction") or "").strip().lower()
    hwy = (way.tags.get("highway") or "").strip().lower()
    return junc in {"roundabout", "circular"} or hwy == "mini_roundabout"


def _bufferable_way(way: OsmWay) -> bool:
    hwy = (way.tags.get("highway") or "").strip()
    if hwy in SKIP_HIGHWAY_MESH:
        return False
    area = (way.tags.get("area") or "").strip().lower()
    if area in {"yes", "true", "1"} and (way.tags.get("junction") or "") != "roundabout":
        return False
    if way.coords_m is None or len(way.coords_m) < 2:
        return False
    return way_width_m(way.tags) > 0


def _same_named_road(a: OsmWay, b: OsmWay) -> bool:
    for key in ("ref", "name:zh", "name", "name:en"):
        va = (a.tags.get(key) or "").strip()
        vb = (b.tags.get(key) or "").strip()
        if va and va == vb:
            return True
    return False


def _same_chain_class(a: OsmWay, b: OsmWay) -> bool:
    ja = (a.tags.get("junction") or "").strip()
    jb = (b.tags.get("junction") or "").strip()
    if ja == "roundabout" or jb == "roundabout":
        return False
    return is_motor_highway(a.tags) == is_motor_highway(b.tags)


def merge_degree2_chains(ways: list[OsmWay], graph_degree: dict | None = None) -> list[OsmWay]:
    """Join ways that belong to one road so a corner becomes an interior vertex (then filleted).

    A node needs smoothing when two incident ways are the same logical road, not a T-stem:
    same name/ref, nearly opposite headings, the only two highest-rank arms, or degree 2.
    """
    if len(ways) < 2:
        return list(ways)
    deg = graph_degree if graph_degree is not None else graph_degree_from_ways(ways)
    parent = list(range(len(ways)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ends: dict[tuple, list[int]] = {}
    for i, way in enumerate(ways):
        if way.closed or not _bufferable_way(way):
            continue
        if _is_roundabout_way(way):
            continue
        coords = way.coords_m
        for xy in (coords[0], coords[-1]):
            ends.setdefault(_node_key(xy), []).append(i)
    for key, idxs in ends.items():
        uniq = list(dict.fromkeys(idxs))
        if len(uniq) < 2:
            continue
        paired = False
        heads: list[tuple[int, float]] = []
        for i in uniq:
            h = _endpoint_heading(ways[i], key)
            if h is not None:
                heads.append((i, h))
        used: set[int] = set()
        for a in range(len(heads)):
            ia, ha = heads[a]
            if ia in used:
                continue
            for b in range(a + 1, len(heads)):
                ib, hb = heads[b]
                if ib in used:
                    continue
                if not _same_chain_class(ways[ia], ways[ib]):
                    continue
                named = _same_named_road(ways[ia], ways[ib])
                if not named and _road_rank(ways[ia].tags) != _road_rank(ways[ib].tags):
                    continue
                if not named and not _headings_opposite(ha, hb):
                    continue
                pi, pj = find(ia), find(ib)
                if pi != pj:
                    parent[pj] = pi
                used.add(ia)
                used.add(ib)
                paired = True
                break
        if paired:
            continue
        bend = _highest_rank_bend_pair(ways, uniq)
        if bend is not None:
            i, j = bend
            pi, pj = find(i), find(j)
            if pi != pj:
                parent[pj] = pi
            continue
        if len(uniq) == 2 and _degree_at(deg, key) == 2:
            i, j = uniq[0], uniq[1]
            if _same_chain_class(ways[i], ways[j]):
                pi, pj = find(i), find(j)
                if pi != pj:
                    parent[pj] = pi
    groups: dict[int, list[int]] = {}
    for i in range(len(ways)):
        groups.setdefault(find(i), []).append(i)
    out: list[OsmWay] = []
    for idxs in groups.values():
        if len(idxs) == 1:
            out.append(ways[idxs[0]])
            continue
        merged = _assemble_chain([ways[i] for i in idxs])
        out.append(merged if merged is not None else ways[idxs[0]])
        if merged is None:
            out.extend(ways[i] for i in idxs[1:])
    return out


def _assemble_chain(group: list[OsmWay]) -> OsmWay | None:
    if len(group) < 2:
        return group[0] if group else None
    unused = set(range(len(group)))
    inc: dict[tuple, list[int]] = {}
    for i, way in enumerate(group):
        inc.setdefault(_node_key(way.coords_m[0]), []).append(i)
        inc.setdefault(_node_key(way.coords_m[-1]), []).append(i)

    def at_node(key) -> list[int]:
        return list(dict.fromkeys(inc.get(key, [])))

    ends = [key for key, vals in inc.items() if len(at_node(key)) == 1]
    current = ends[0] if ends else _node_key(group[0].coords_m[0])
    ordered: list[tuple[float, float]] = []
    ordered_w: list[float] = []
    while unused:
        cand = [i for i in at_node(current) if i in unused]
        if not cand:
            break
        idx = cand[0]
        unused.remove(idx)
        oriented = _orient_from_node(group[idx].coords_m, current)
        if oriented is None:
            return None
        width = way_width_m(group[idx].tags)
        if not ordered:
            ordered = oriented
            ordered_w = [width] * len(oriented)
        else:
            ordered.extend(oriented[1:])
            ordered_w.extend([width] * (len(oriented) - 1))
        current = _node_key(ordered[-1])
    if unused or len(ordered) < 2 or len(ordered_w) != len(ordered):
        return None
    longest = max(group, key=lambda w: max(0.0, LineString(w.coords_m).length if w.coords_m else 0.0))
    closed = len(ordered) >= 4 and _node_key(ordered[0]) == _node_key(ordered[-1])
    return OsmWay(
        osm_id=longest.osm_id,
        tags=dict(longest.tags),
        coords_m=ordered,
        closed=closed,
        vertex_width_m=ordered_w,
    )


def _highest_rank_bend_pair(ways: list[OsmWay], uniq: list[int]) -> tuple[int, int] | None:
    """If exactly two highest-rank arms meet here, they are one road turning a corner."""
    if len(uniq) < 2:
        return None
    ranks = [_road_rank(ways[i].tags) for i in uniq]
    max_r = min(ranks)
    top = [i for i, r in zip(uniq, ranks) if r == max_r]
    if len(top) != 2:
        return None
    i, j = top[0], top[1]
    if not _same_chain_class(ways[i], ways[j]):
        return None
    return i, j


def _endpoint_heading(way: OsmWay, node_key) -> float | None:
    coords = way.coords_m
    if coords is None or len(coords) < 2:
        return None
    if _node_key(coords[0]) == node_key:
        return math.atan2(float(coords[1][1]) - float(coords[0][1]), float(coords[1][0]) - float(coords[0][0]))
    if _node_key(coords[-1]) == node_key:
        n = len(coords)
        return math.atan2(float(coords[n - 2][1]) - float(coords[n - 1][1]), float(coords[n - 2][0]) - float(coords[n - 1][0]))
    return None


def _orient_from_node(coords, node_key) -> list | None:
    if _node_key(coords[0]) == node_key:
        return [(float(x), float(y)) for x, y in coords]
    if _node_key(coords[-1]) == node_key:
        return [(float(x), float(y)) for x, y in reversed(coords)]
    return None


def _fillet_polyline(coords, radius_m: float) -> list[tuple[float, float]]:
    """Replace sharp interior vertices with circular arcs so pavement and markings follow the bend."""
    if coords is None or len(coords) < 3 or radius_m < 0.35:
        return list(coords or [])
    closed = _node_key(coords[0]) == _node_key(coords[-1]) and len(coords) >= 4
    body = list(coords[:-1]) if closed else list(coords)
    n = len(body)
    if n < 3:
        return list(coords)

    def vtx(i: int):
        return body[i % n]

    out: list[tuple[float, float]] = []
    if not closed:
        out.append((float(body[0][0]), float(body[0][1])))
    indices = range(n) if closed else range(1, n - 1)
    for i in indices:
        arc = _fillet_vertex(vtx(i - 1), vtx(i), vtx(i + 1), radius_m)
        if arc is None:
            pt = vtx(i)
            out.append((float(pt[0]), float(pt[1])))
        else:
            out.extend(arc)
    if not closed:
        out.append((float(body[-1][0]), float(body[-1][1])))
    elif out:
        out.append(out[0])
    return out if len(out) >= 2 else list(coords)


def _fillet_vertex(prev, curr, nxt, radius_m: float):
    x0, y0 = float(prev[0]), float(prev[1])
    x1, y1 = float(curr[0]), float(curr[1])
    x2, y2 = float(nxt[0]), float(nxt[1])
    inx, iny = x1 - x0, y1 - y0
    outx, outy = x2 - x1, y2 - y1
    len_in = math.hypot(inx, iny)
    len_out = math.hypot(outx, outy)
    if len_in < 0.25 or len_out < 0.25:
        return None
    uix, uiy = inx / len_in, iny / len_in
    uox, uoy = outx / len_out, outy / len_out
    dot = max(-1.0, min(1.0, uix * uox + uiy * uoy))
    theta = math.acos(dot)
    if theta < 0.10 or theta > math.pi - 0.08:
        return None
    radius = min(float(radius_m), len_in * 0.48, len_out * 0.48)
    cut = min(len_in * 0.45, len_out * 0.45, max(0.35, radius * math.tan(max(theta * 0.5, 0.05))))
    p1 = (x1 - uix * cut, y1 - uiy * cut)
    p2 = (x1 + uox * cut, y1 + uoy * cut)
    if radius < 0.35:
        return _bezier_corner(p1, (x1, y1), p2, theta)
    tangent = radius * math.tan(theta * 0.5)
    if tangent < 0.2 or tangent > cut + 1e-6:
        return _bezier_corner(p1, (x1, y1), p2, theta)
    p1 = (x1 - uix * tangent, y1 - uiy * tangent)
    p2 = (x1 + uox * tangent, y1 + uoy * tangent)
    cross = uix * uoy - uiy * uox
    if cross >= 0.0:
        nx, ny = -uiy, uix
        ccw = True
    else:
        nx, ny = uiy, -uix
        ccw = False
    cx, cy = p1[0] + nx * radius, p1[1] + ny * radius
    a0 = math.atan2(p1[1] - cy, p1[0] - cx)
    a1 = math.atan2(p2[1] - cy, p2[0] - cx)
    if ccw:
        if a1 <= a0:
            a1 += 2.0 * math.pi
        sweep = a1 - a0
    else:
        if a1 >= a0:
            a1 -= 2.0 * math.pi
        sweep = a0 - a1
    arc_len = radius * max(sweep, 0.2)
    steps = max(16, int(math.ceil(arc_len / 0.35)))
    pts = []
    for s in range(steps + 1):
        t = s / float(steps)
        ang = a0 + (a1 - a0) * t
        pts.append((cx + math.cos(ang) * radius, cy + math.sin(ang) * radius))
    return pts


def _bezier_corner(p1, ctrl, p2, theta: float):
    steps = max(16, int(math.degrees(max(theta, 0.3)) / 3.0))
    pts = []
    x0, y0 = p1
    x1, y1 = ctrl
    x2, y2 = p2
    for s in range(steps + 1):
        t = s / float(steps)
        u = 1.0 - t
        pts.append(
            (
                u * u * x0 + 2.0 * u * t * x1 + t * t * x2,
                u * u * y0 + 2.0 * u * t * y1 + t * t * y2,
            )
        )
    return pts


def _variable_width_polygon(coords, widths: list[float]):
    if coords is None or len(coords) < 2 or not widths or len(widths) != len(coords):
        return None
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    n = len(coords)
    for i in range(n):
        nx, ny = _normal_at(coords, i)
        h = max(0.4, float(widths[i]) * 0.5)
        x, y = float(coords[i][0]), float(coords[i][1])
        left.append((x + nx * h, y + ny * h))
        right.append((x - nx * h, y - ny * h))
    poly = Polygon(left + list(reversed(right)))
    if poly is None or poly.is_empty:
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly is None or poly.is_empty:
        return None
    return poly


def _normal_at(coords, i: int) -> tuple[float, float]:
    n = len(coords)
    if n < 2:
        return (0.0, 1.0)
    if i <= 0:
        dx = float(coords[1][0]) - float(coords[0][0])
        dy = float(coords[1][1]) - float(coords[0][1])
    elif i >= n - 1:
        dx = float(coords[n - 1][0]) - float(coords[n - 2][0])
        dy = float(coords[n - 1][1]) - float(coords[n - 2][1])
    else:
        dx = float(coords[i + 1][0]) - float(coords[i - 1][0])
        dy = float(coords[i + 1][1]) - float(coords[i - 1][1])
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return (0.0, 1.0)
    return (-dy / length, dx / length)


def _remap_widths(old_xy, old_w: list[float], new_xy, stepwise: bool = False) -> list[float]:
    if not old_xy or not old_w or not new_xy:
        return [old_w[0] if old_w else 6.0] * max(1, len(new_xy or []))
    stations = [0.0]
    for i in range(1, len(old_xy)):
        stations.append(
            stations[-1]
            + math.hypot(float(old_xy[i][0]) - float(old_xy[i - 1][0]), float(old_xy[i][1]) - float(old_xy[i - 1][1]))
        )
    total = stations[-1]
    line = LineString(old_xy)
    out: list[float] = []
    for p in new_xy:
        try:
            d = float(line.project(Point(float(p[0]), float(p[1]))))
        except Exception:
            d = 0.0
        d = d if total > 0 else 0.0
        out.append(_step_along(stations, old_w, d) if stepwise else _lerp_along(stations, old_w, d))
    return out


def _lerp_along(stations: list[float], values: list[float], d: float) -> float:
    if d <= stations[0]:
        return float(values[0])
    if d >= stations[-1]:
        return float(values[-1])
    for i in range(1, len(stations)):
        if d <= stations[i]:
            span = stations[i] - stations[i - 1]
            t = 0.0 if span < 1e-9 else (d - stations[i - 1]) / span
            return float(values[i - 1]) * (1.0 - t) + float(values[i]) * t
    return float(values[-1])


def _step_along(stations: list[float], values: list[float], d: float) -> float:
    if d <= stations[0]:
        return float(values[0])
    for i in range(1, len(stations)):
        if d <= stations[i] + 1e-9:
            return float(values[i])
    return float(values[-1])


def _densify_width_blend(coords, widths: list[float], step_m: float = 2.0):
    if coords is None or len(coords) < 2:
        return list(coords or []), list(widths or [])
    if len(widths) != len(coords):
        widths = [widths[0] if widths else 6.0] * len(coords)
    delta = 0.0
    for i in range(1, len(widths)):
        delta = max(delta, abs(float(widths[i]) - float(widths[i - 1])))
    if delta <= 0.2:
        return [(float(p[0]), float(p[1])) for p in coords], [float(w) for w in widths]
    xy: list[tuple[float, float]] = [(float(coords[0][0]), float(coords[0][1]))]
    ww: list[float] = [float(widths[0])]
    for i in range(len(coords) - 1):
        x0, y0 = float(coords[i][0]), float(coords[i][1])
        x1, y1 = float(coords[i + 1][0]), float(coords[i + 1][1])
        w0, w1 = float(widths[i]), float(widths[i + 1])
        dist = math.hypot(x1 - x0, y1 - y0)
        if dist < 1e-4:
            continue
        n = max(1, int(math.ceil(dist / step_m)))
        for k in range(1, n + 1):
            t = k / float(n)
            xy.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            ww.append(w1 if abs(w1 - w0) > 0.2 else w0)
    if len(ww) < 3:
        return xy, ww
    radius = max(2, int(min(20.0, max(10.0, 2.0 * delta)) / step_m))
    smooth = []
    n = len(ww)
    for i in range(n):
        lo = max(0, i - radius)
        hi = min(n, i + radius + 1)
        smooth.append(sum(ww[lo:hi]) / float(hi - lo))
    return xy, smooth


def build_road_polygons(ways: list[OsmWay]) -> list[tuple[OsmWay, object]]:
    """LineString buffer by half-width; skip <2 coords and OSM junction areas."""
    filtered = [w for w in ways if _bufferable_way(w)]
    merged = merge_degree2_chains(filtered, graph_degree_from_ways(ways))
    out: list[tuple[OsmWay, object]] = []
    for way in merged:
        width = way_width_m(way.tags)
        raw_w = way.vertex_width_m
        if not raw_w or len(raw_w) != len(way.coords_m):
            raw_w = [width] * len(way.coords_m)
        max_w = max(raw_w) if raw_w else width
        coords = _fillet_polyline(way.coords_m, min(16.0, max(4.0, max_w * 0.9)))
        if len(coords) < 2:
            continue
        widths = _remap_widths(way.coords_m, raw_w, coords, stepwise=True)
        coords, widths = _densify_width_blend(coords, widths)
        line = LineString(coords)
        if line.is_empty or line.length == 0:
            continue
        poly = _variable_width_polygon(coords, widths)
        if poly is None or getattr(poly, "is_empty", True):
            poly = line.buffer(width / 2.0, cap_style="flat", join_style="round")
        if poly is None or poly.is_empty:
            continue
        out.append((OsmWay(way.osm_id, way.tags, coords, way.closed, widths), poly))
    return out


def subtract_road_hierarchy(
    buffered: list[tuple[OsmWay, object]],
) -> list[tuple[OsmWay, object]]:
    """Higher rank cuts lower rank. Remaining overlaps: keep one face (no city-wide union)."""
    if not buffered:
        return []

    originals = list(buffered)
    valid_idx: list[int] = []
    valid_geoms: list = []
    for i, (_way, geom) in enumerate(originals):
        if geom is None or getattr(geom, "is_empty", True):
            continue
        valid_idx.append(i)
        valid_geoms.append(geom)
    tree = STRtree(valid_geoms) if valid_geoms else None

    result: list[tuple[OsmWay, object]] = []
    for way, geom in originals:
        cut = geom
        if tree is None or geom is None or getattr(geom, "is_empty", True):
            result.append((way, cut))
            continue
        rank = _road_rank(way.tags)
        hits = tree.query(geom, predicate="intersects")
        for local_j in hits:
            other_way, other_geom = originals[valid_idx[int(local_j)]]
            if other_way is way:
                continue
            if other_geom is None or getattr(other_geom, "is_empty", True):
                continue
            if _grade_key(way.tags) != _grade_key(other_way.tags):
                continue
            if _road_rank(other_way.tags) < rank:
                cut = difference_safe(cut, other_geom)
        result.append((way, cut))

    out = list(result)
    valid_out: list[int] = []
    valid_out_geoms: list = []
    for i, (_w, g) in enumerate(out):
        if g is None or getattr(g, "is_empty", True):
            continue
        valid_out.append(i)
        valid_out_geoms.append(g)
    if len(valid_out_geoms) < 2:
        return out
    clip_tree = STRtree(valid_out_geoms)
    for local_i, i in enumerate(valid_out):
        way_i, geom_i = out[i]
        if geom_i is None or getattr(geom_i, "is_empty", True):
            continue
        hits = clip_tree.query(geom_i, predicate="intersects")
        for raw_j in hits:
            local_j = int(raw_j)
            if local_j <= local_i:
                continue
            j = valid_out[local_j]
            way_j, geom_j = out[j]
            if geom_j is None or getattr(geom_j, "is_empty", True):
                continue
            if _grade_key(way_i.tags) != _grade_key(way_j.tags):
                continue
            try:
                inter = geom_i.intersection(geom_j)
            except Exception:
                continue
            if inter is None or getattr(inter, "is_empty", True):
                continue
            if getattr(inter, "area", 0.0) < _MIN_OVERLAP_AREA_M2:
                continue
            rank_i = _road_rank(way_i.tags)
            rank_j = _road_rank(way_j.tags)
            cut_j = rank_j > rank_i or (
                rank_j == rank_i and int(way_j.osm_id or 0) >= int(way_i.osm_id or 0)
            )
            if cut_j:
                out[j] = (way_j, difference_safe(geom_j, geom_i))
            else:
                out[i] = (way_i, difference_safe(geom_i, geom_j))
                way_i, geom_i = out[i]
                if geom_i is None or getattr(geom_i, "is_empty", True):
                    break
    return out


def _grade_key(_tags: dict[str, str]) -> tuple[str, str]:
    """All carriageways are coplanar; OSM layer/bridge tags no longer separate meshes."""
    return ("ground", "0")


def way_elevation_m(tags: dict[str, str]) -> float:
    """All carriageways stay on the ground; no OSM layer/bridge deck offset."""
    return 0.0


def junction_clearance_polygons(ways: list[OsmWay], graph_degree: dict, buffered=None) -> list:
    """Typed junction patches (T / cross / Y / roundabout), not covering disks."""
    return [j["geom"] for j in build_typed_junctions(ways, graph_degree, buffered) if j.get("geom") is not None]


def build_typed_junctions(ways: list[OsmWay], graph_degree: dict, buffered=None) -> list[dict]:
    """一级路：T / 十字 / Y / 环岛（仅作标线裁剪窗口，不另写路口盖面）。"""
    if not ways or not graph_degree:
        return []
    geom_by_id = {}
    if buffered:
        for way, geom in buffered:
            if way.osm_id is not None:
                geom_by_id[way.osm_id] = geom
    roundabout_nodes: set[tuple] = set()
    out: list[dict] = []
    for way in ways:
        if not _is_roundabout_way(way):
            continue
        if not is_primary_junction_highway(way.tags):
            continue
        patch = _roundabout_patch(way)
        if patch is None:
            continue
        out.append({"kind": "roundabout", "geom": patch, "xy": _poly_xy(patch), "stop": [], "zebra": []})
        if way.coords_m:
            for xy in way.coords_m:
                roundabout_nodes.add(_node_key(xy))

    node_ways: dict[tuple, list] = {}
    for way in ways:
        if not is_motor_highway(way.tags):
            continue
        if _is_roundabout_way(way):
            continue
        if way.coords_m is None or len(way.coords_m) < 2:
            continue
        seen_n: set[tuple] = set()
        for xy in way.coords_m:
            key = _node_key(xy)
            if key in seen_n:
                continue
            seen_n.add(key)
            if _degree_at(graph_degree, xy) < 3:
                continue
            if key in roundabout_nodes:
                continue
            node_ways.setdefault(key, []).append(way)

    primary_cands: list[dict] = []
    for key, inc_ways in node_ways.items():
        ids = {w.osm_id for w in inc_ways if w.osm_id is not None}
        if len(ids) < 2:
            continue
        grades = {_grade_key(w.tags) for w in inc_ways}
        if len(grades) != 1:
            continue
        n_primary = sum(1 for w in inc_ways if is_primary_junction_highway(w.tags))
        if n_primary < 2:
            continue
        xy = (float(key[0]), float(key[1]))
        primary_cands.append({"xy": xy, "ways": inc_ways})

    for cluster in _cluster_junction_candidates(primary_cands, JUNCTION_CLUSTER_M):
        built = _build_cluster_junction(cluster, geom_by_id)
        if built is not None:
            out.append(built)
    return out


def _cluster_junction_candidates(cands: list[dict], dist_m: float) -> list[list[dict]]:
    n = len(cands)
    if n == 0:
        return []
    if n == 1:
        return [cands]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    d2 = float(dist_m) * float(dist_m)
    for i in range(n):
        xi, yi = cands[i]["xy"]
        for j in range(i + 1, n):
            dx = xi - cands[j]["xy"][0]
            dy = yi - cands[j]["xy"][1]
            if dx * dx + dy * dy <= d2:
                parent[find(j)] = find(i)
    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cands[i])
    return list(groups.values())


def _build_cluster_junction(cluster: list[dict], geom_by_id: dict):
    _ = geom_by_id
    ways: list = []
    seen_ids: set = set()
    xs: list[float] = []
    ys: list[float] = []
    widths: list[float] = []
    raw_arms: list[float] = []
    for item in cluster:
        xy = item["xy"]
        xs.append(float(xy[0]))
        ys.append(float(xy[1]))
        for w in item["ways"]:
            widths.append(way_width_m(w.tags))
            raw_arms.extend(_junction_arms([w], xy))
            oid = w.osm_id
            if oid is not None and oid in seen_ids:
                continue
            if oid is not None:
                seen_ids.add(oid)
            ways.append(w)
    if len(ways) < 2:
        return None
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    centroid = (cx, cy)
    max_w = max(widths) if widths else 12.0
    arms = _cluster_headings(raw_arms)
    kind = classify_junction_kind(arms) if len(arms) >= 3 else "disk"
    if kind not in {"tee", "wye", "cross"}:
        return None
    nodes = list(zip(xs, ys))
    clip_r = max(4.0, max_w * 0.5 + 0.8)
    try:
        core = MultiPoint(nodes).convex_hull if len(nodes) > 1 else Point(cx, cy)
        patch = core.buffer(float(clip_r))
    except Exception:
        patch = Point(cx, cy).buffer(float(clip_r))
    if patch is None or getattr(patch, "is_empty", True):
        return None
    stop, zebra = _junction_approach_markings(kind, arms, centroid, nodes, max_w)
    return {"kind": kind, "geom": patch, "xy": centroid, "stop": stop, "zebra": zebra}


def classify_junction_kind(arms: list[float]) -> str:
    """tee / wye / cross / irregular from outbound arm headings."""
    n = len(arms)
    if n <= 2:
        return "none"
    opposites = 0
    used = [False] * n
    for i in range(n):
        if used[i]:
            continue
        for j in range(i + 1, n):
            if used[j]:
                continue
            if _headings_opposite(arms[i], arms[j]):
                opposites += 1
                used[i] = used[j] = True
                break
    if n == 3:
        return "tee" if opposites >= 1 else "wye"
    if n == 4:
        return "cross" if opposites >= 2 else "irregular"
    return "complex"


def _junction_arms(ways: list[OsmWay], xy) -> list[float]:
    raw: list[float] = []
    nx, ny = float(xy[0]), float(xy[1])
    for way in ways:
        coords = way.coords_m
        n = len(coords)
        for i, pt in enumerate(coords):
            if abs(float(pt[0]) - nx) > 1e-3 or abs(float(pt[1]) - ny) > 1e-3:
                continue
            if i > 0:
                raw.append(math.atan2(float(coords[i - 1][1]) - ny, float(coords[i - 1][0]) - nx))
            if i < n - 1:
                raw.append(math.atan2(float(coords[i + 1][1]) - ny, float(coords[i + 1][0]) - nx))
    return _cluster_headings(raw)


def _cluster_headings(raw: list[float]) -> list[float]:
    arms: list[float] = []
    for h in raw:
        matched = False
        for i, a in enumerate(arms):
            if _ang_abs(h - a) < _ARM_HEADING_TOL:
                arms[i] = a
                matched = True
                break
        if not matched:
            arms.append(h)
    return arms


def _headings_opposite(a: float, b: float) -> bool:
    return _ang_abs(a - b - math.pi) < _OPPOSITE_TOL or _ang_abs(a - b + math.pi) < _OPPOSITE_TOL


def _ang_abs(d: float) -> float:
    while d > math.pi:
        d -= 2.0 * math.pi
    while d < -math.pi:
        d += 2.0 * math.pi
    return abs(d)


def _roundabout_patch(way: OsmWay):
    coords = way.coords_m
    if coords is None or len(coords) < 3:
        return None
    width = max(5.0, way_width_m(way.tags))
    if way.closed:
        ring = LineString(coords)
        if ring.length < 8:
            try:
                return Polygon(coords) if len(coords) >= 4 else Point(coords[0]).buffer(8.0)
            except Exception:
                return Point(float(coords[0][0]), float(coords[0][1])).buffer(max(6.0, width))
        try:
            road = ring.buffer(width * 0.5 + 0.8)
            if road is not None and not road.is_empty:
                return road
        except Exception:
            pass
        try:
            return ring.buffer(width * 0.5)
        except Exception:
            return Point(float(coords[0][0]), float(coords[0][1])).buffer(max(6.0, width))
    line = LineString(coords)
    if line.is_empty or line.length < 1.0:
        return Point(float(coords[0][0]), float(coords[0][1])).buffer(max(6.0, width))
    try:
        return line.buffer(width * 0.5 + 1.5)
    except Exception:
        return Point(float(coords[0][0]), float(coords[0][1])).buffer(max(6.0, width))


def _poly_xy(geom) -> tuple[float, float]:
    c = geom.centroid
    return (float(c.x), float(c.y))


def _junction_approach_markings(kind: str, arms: list[float], xy, nodes: list, width_m: float):
    stop: list = []
    zebra: list = []
    if kind not in ("tee", "cross", "wye"):
        return stop, zebra
    through = set()
    if kind == "tee":
        n = len(arms)
        for i in range(n):
            for j in range(i + 1, n):
                if _headings_opposite(arms[i], arms[j]):
                    through.add(i)
                    through.add(j)
                    break
    inbound = [i for i in range(len(arms)) if i not in through] if kind == "tee" else list(range(len(arms)))
    span = max(5.0, float(width_m) * 0.92)
    pitch = CROSSWALK_STRIPE_M + CROSSWALK_GAP_M
    node_xy = list(nodes or [xy])
    for i in inbound:
        h = arms[i]
        ux, uy = math.cos(h), math.sin(h)
        proj = 0.0
        for nx, ny in node_xy:
            proj = max(proj, (float(nx) - float(xy[0])) * ux + (float(ny) - float(xy[1])) * uy)
        d_zebra0 = proj + float(width_m) * 0.5 + 1.2
        for s in range(CROSSWALK_STRIPES):
            t = d_zebra0 + s * pitch
            zx = float(xy[0]) + ux * t
            zy = float(xy[1]) + uy * t
            zebra.append(_oriented_box(zx, zy, -uy, ux, CROSSWALK_STRIPE_M, span * 0.9))
    return [], [p for p in zebra if p is not None]


def split_line_coords_at_junctions(coords, junction_pts: list, tree=None, setback_m: float = 5.0) -> list:
    """Cut a way into pieces that stop short of degree>=3 nodes so markings do not form a Y."""
    if coords is None or len(coords) < 2 or not junction_pts:
        return [list(coords)] if coords is not None and len(coords) >= 2 else []
    line = LineString(coords)
    if line.is_empty or line.length < 1.0:
        return [list(coords)]
    if tree is None:
        tree = STRtree(junction_pts)
    hits = tree.query(line, predicate="intersects")
    windows: list[tuple[float, float]] = []
    setback = float(setback_m)
    for raw in hits:
        pt = junction_pts[int(raw)]
        try:
            if line.distance(pt) > 0.75:
                continue
            d = line.project(pt)
        except Exception:
            continue
        if _line_bends_near(line, d, window_m=max(4.0, setback * 0.8)):
            continue
        windows.append((d - setback, d + setback))
    if not windows:
        return [list(coords)]
    pieces = _cut_line_windows(line, windows)
    out = []
    for piece in pieces:
        pts = list(piece.coords)
        if len(pts) >= 2:
            out.append(pts)
    return out


def _line_bends_near(line, d: float, window_m: float = 4.0) -> bool:
    """True when an interior centerline turns here — keep a continuous arc, do not gap markings."""
    length = float(line.length)
    if length < 2.0:
        return False
    along = float(d)
    if along < 1.25 or along > length - 1.25:
        return False
    span = max(2.0, float(window_m))
    d0 = max(0.0, along - span)
    d1 = min(length, along + span)
    if d1 - d0 < 1.5:
        return False
    p0 = line.interpolate(d0)
    p1 = line.interpolate(max(d0, min(d1, along)))
    p2 = line.interpolate(d1)
    ha = math.atan2(p1.y - p0.y, p1.x - p0.x)
    hb = math.atan2(p2.y - p1.y, p2.x - p1.x)
    return _ang_abs(hb - ha) > math.radians(16.0)


def _cut_line_windows(line, windows: list[tuple[float, float]]):
    length = float(line.length)
    merged: list[list[float]] = []
    for a, b in sorted(windows):
        a = max(0.0, float(a))
        b = min(length, float(b))
        if b <= a:
            continue
        if not merged or a > merged[-1][1]:
            merged.append([a, b])
        else:
            merged[-1][1] = max(merged[-1][1], b)
    out = []
    pos = 0.0
    min_keep = 1.0
    for a, b in merged:
        if a - pos >= min_keep:
            piece = substring(line, pos, a)
            if piece is not None and not piece.is_empty and piece.length >= min_keep:
                out.append(piece)
        pos = b
    if length - pos >= min_keep:
        piece = substring(line, pos, length)
        if piece is not None and not piece.is_empty and piece.length >= min_keep:
            out.append(piece)
    return out


def _oriented_box(cx: float, cy: float, ux: float, uy: float, thick: float, span: float):
    rx, ry = -uy, ux
    ht, hs = thick * 0.5, span * 0.5
    pts = [
        (cx + ux * ht + rx * hs, cy + uy * ht + ry * hs),
        (cx + ux * ht - rx * hs, cy + uy * ht - ry * hs),
        (cx - ux * ht - rx * hs, cy - uy * ht - ry * hs),
        (cx - ux * ht + rx * hs, cy - uy * ht + ry * hs),
    ]
    poly = Polygon(pts)
    if poly.is_empty or not poly.is_valid:
        poly = poly.buffer(0)
    if poly is None or poly.is_empty:
        return None
    return poly


def subtract_junction_disks(ranked, disks: list) -> list:
    if not ranked or not disks:
        return ranked
    tree = STRtree(disks)
    out = []
    for way, geom in ranked:
        cut = geom
        if cut is None or getattr(cut, "is_empty", True):
            out.append((way, cut))
            continue
        hits = tree.query(cut, predicate="intersects")
        for raw in hits:
            cut = difference_safe(cut, disks[int(raw)])
        out.append((way, cut))
    return out


def clip_marking_to_road(marking, road_geom, edge_slack_m: float = 0.25):
    """Keep markings only on this way's remaining pavement (higher-rank road wins the overlap)."""
    if marking is None or getattr(marking, "is_empty", True):
        return marking
    if road_geom is None or getattr(road_geom, "is_empty", True):
        return None
    try:
        clip = road_geom.buffer(float(edge_slack_m))
    except Exception:
        clip = road_geom
    if clip is None or getattr(clip, "is_empty", True):
        return None
    try:
        return marking.intersection(clip)
    except Exception:
        return marking


def clip_geom_by_disks(geom, disks: list, tree=None):
    if geom is None or getattr(geom, "is_empty", True) or not disks:
        return geom
    if tree is None:
        tree = STRtree(disks)
    hits = tree.query(geom, predicate="intersects")
    cut = geom
    for raw in hits:
        cut = difference_safe(cut, disks[int(raw)])
        if cut is None or getattr(cut, "is_empty", True):
            return cut
    return cut


def point_in_disks(xy, disks: list, tree=None) -> bool:
    if not disks:
        return False
    pt = Point(float(xy[0]), float(xy[1]))
    if tree is None:
        tree = STRtree(disks)
    hits = tree.query(pt, predicate="intersects")
    for raw in hits:
        disk = disks[int(raw)]
        try:
            if disk.covers(pt) or disk.intersects(pt):
                return True
        except Exception:
            continue
    return False


def marking_kind(tags: dict[str, str], width_m: float) -> dict:
    """Return {center, lane, edge} per spec table."""
    hwy = tags.get("highway", "")
    if hwy in ("motorway", "trunk", "primary"):
        return {
            "center": "double_yellow_solid",
            "lane": "white_dash",
            "edge": "white_solid",
        }
    if hwy == "secondary":
        center = "double_yellow_solid" if width_m >= 9 else "single_yellow_solid"
        return {"center": center, "lane": "white_dash", "edge": "white_solid"}
    if hwy == "tertiary":
        lane = "white_dash" if width_m >= 8 else "none"
        return {"center": "single_yellow_dash", "lane": lane, "edge": "none"}
    if hwy == "residential":
        center = "single_white_dash" if width_m >= 6 else "none"
        return {"center": center, "lane": "none", "edge": "none"}
    return {"center": "none", "lane": "none", "edge": "none"}


def offset_polylines(coords_m, width_m, vertex_width_m=None) -> dict:
    """Centerline plus left/right edge lines for marking meshes."""
    empty = {"center": None, "left": None, "right": None}
    if coords_m is None or len(coords_m) < 2:
        return empty
    line = LineString(coords_m)
    if line.is_empty:
        return {"center": line, "left": line, "right": line}
    widths = vertex_width_m
    if widths is not None and len(widths) == len(coords_m):
        return {
            "center": line,
            "left": _offset_line_variable(coords_m, widths, 0.5),
            "right": _offset_line_variable(coords_m, widths, -0.5),
        }
    half = float(width_m) / 2.0
    left = _parallel_offset(line, half, "left")
    right = _parallel_offset(line, half, "right")
    return {"center": line, "left": left, "right": right}


def _offset_line_variable(coords, widths: list[float], frac: float):
    pts = []
    for i, (x, y) in enumerate(coords):
        nx, ny = _normal_at(coords, i)
        h = float(widths[i]) * float(frac)
        pts.append((float(x) + nx * h, float(y) + ny * h))
    if len(pts) < 2:
        return None
    line = LineString(pts)
    return None if line.is_empty else line


def widths_along_piece(way: OsmWay, piece) -> list | None:
    vw = getattr(way, "vertex_width_m", None)
    if not vw or piece is None or way.coords_m is None:
        return None
    if len(vw) != len(way.coords_m):
        return None
    return _remap_widths(way.coords_m, vw, piece)


def marking_strip_polygons(coords_m, tags: dict[str, str], width_m: Optional[float] = None, vertex_width_m=None) -> list[dict]:
    """Thin LineString.buffer(0.08) marking strips. z = roads + 0.01 m."""
    if coords_m is None or len(coords_m) < 2:
        return []
    if width_m is None:
        width_m = way_width_m(tags)
    kind = marking_kind(tags, width_m)
    vary = vertex_width_m if vertex_width_m is not None and len(vertex_width_m) == len(coords_m) else None
    offsets = offset_polylines(coords_m, width_m, vary)
    strips: list[dict] = []

    center_style = kind["center"]
    if center_style == "double_yellow_solid":
        center = offsets["center"]
        if center is not None and not center.is_empty:
            half = DOUBLE_YELLOW_SEP_M / 2.0
            for side in ("left", "right"):
                line = _parallel_offset(center, half, side)
                strips.extend(_buffer_marking(line, "center", center_style))
    elif center_style != "none":
        strips.extend(_buffer_marking(offsets["center"], "center", center_style))

    if kind["lane"] == "white_dash" and width_m > 0:
        if vary is not None:
            for frac in (0.25, -0.25):
                line = _offset_line_variable(coords_m, vary, frac)
                strips.extend(_buffer_marking(line, "lane", "white_dash"))
        else:
            center = offsets["center"]
            if center is not None and not center.is_empty:
                quarter = float(width_m) / 4.0
                for side in ("left", "right"):
                    line = _parallel_offset(center, quarter, side)
                    strips.extend(_buffer_marking(line, "lane", "white_dash"))

    if kind["edge"] == "white_solid":
        strips.extend(_buffer_marking(offsets["left"], "edge", "white_solid"))
        strips.extend(_buffer_marking(offsets["right"], "edge", "white_solid"))

    return strips


def graph_degree_from_ways(ways: list[OsmWay]) -> dict:
    """Count incident segments per rounded node, so an unsplit through-road at a T counts as 2."""
    deg: dict = {}
    if not ways:
        return deg
    for way in ways:
        coords = way.coords_m
        if coords is None or len(coords) < 2:
            continue
        for i in range(len(coords) - 1):
            a = _node_key(coords[i])
            b = _node_key(coords[i + 1])
            if a == b:
                continue
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
    return deg


def _looks_like_roundabout_ring(coords, closed: bool) -> bool:
    """Compact loop or near-loop: arrows on the ring are not junction-approach arrows."""
    if coords is None or len(coords) < 8:
        return False
    try:
        length = float(LineString(coords).length)
    except Exception:
        return False
    if length < 40.0 or length > 900.0:
        return False
    turn = 0.0
    for i in range(1, len(coords) - 1):
        x0, y0 = float(coords[i - 1][0]), float(coords[i - 1][1])
        x1, y1 = float(coords[i][0]), float(coords[i][1])
        x2, y2 = float(coords[i + 1][0]), float(coords[i + 1][1])
        a = math.atan2(y1 - y0, x1 - x0)
        b = math.atan2(y2 - y1, x2 - x1)
        turn += _ang_abs(b - a)
    if closed or _node_key(coords[0]) == _node_key(coords[-1]):
        return turn > math.radians(250.0)
    return turn > math.radians(200.0)


def _point_in_geoms(xy, geoms: list) -> bool:
    if not geoms:
        return False
    pt = Point(float(xy[0]), float(xy[1]))
    for geom in geoms:
        try:
            if geom.covers(pt) or geom.distance(pt) < 0.4:
                return True
        except Exception:
            continue
    return False


def _dedupe_arrows(arrows: list[dict], min_perp_m: float = 4.2, min_same_m: float = 14.0) -> list[dict]:
    """Drop stacked arrows: same heading too close, or crossing arrows on top of each other."""
    kept: list[dict] = []
    for a in arrows:
        ax, ay = float(a["xy"][0]), float(a["xy"][1])
        ayaw = float(a["yaw_rad"])
        drop = False
        for b in kept:
            d = math.hypot(ax - float(b["xy"][0]), ay - float(b["xy"][1]))
            dh = _ang_abs(ayaw - float(b["yaw_rad"]))
            same = dh < 0.35
            perp = 0.55 < dh < math.pi - 0.55
            if same and d < min_same_m:
                drop = True
                break
            if perp and d < min_perp_m:
                drop = True
                break
        if not drop:
            kept.append(a)
    return kept


def junction_arrows(buffered, graph_degree: dict) -> list:
    """One inbound arrow per approach at deg>=3, aligned to the lane. None on roundabouts."""
    arrows: list[dict] = []
    if not buffered or not graph_degree:
        return arrows

    ra_geoms: list = []
    for way, _geom in buffered:
        if not _is_roundabout_way(way):
            continue
        patch = _roundabout_patch(way)
        if patch is not None and not getattr(patch, "is_empty", True):
            ra_geoms.append(patch)

    seen: set[tuple] = set()
    for way, _geom in buffered:
        if way.tags.get("highway") == "junction":
            continue
        if _is_roundabout_way(way) or way.closed:
            continue
        if _looks_like_roundabout_ring(way.coords_m, way.closed):
            continue
        if not is_major_highway(way.tags):
            continue
        coords = way.coords_m
        if coords is None or len(coords) < 2:
            continue
        n = len(coords)
        width = way_width_m(way.tags)
        offsets = inbound_lane_offsets_m(way.tags, width)
        setback = max(ARROW_SETBACK_M, width * 0.55 + JUNCTION_EXTRA_M + 2.5)
        for i, xy in enumerate(coords):
            if int(graph_degree.get(_node_key(xy), 0)) < 3:
                continue
            approaches: list[int] = []
            if i > 0:
                approaches.append(-1)
            if i < n - 1:
                approaches.append(1)
            for step in approaches:
                for offset in offsets:
                    placed = _arrow_on_approach(coords, i, step, offset, setback)
                    if placed is None:
                        continue
                    poly, center_xy, yaw = placed
                    if _point_in_geoms(center_xy, ra_geoms):
                        continue
                    key = (
                        round(center_xy[0] * 2.0) / 2.0,
                        round(center_xy[1] * 2.0) / 2.0,
                        round(yaw, 2),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    arrows.append(
                        {
                            "poly": poly,
                            "xy": center_xy,
                            "yaw_rad": yaw,
                            "osm_id": way.osm_id,
                        }
                    )
    return _dedupe_arrows(arrows)


def way_display_name(tags: dict[str, str]) -> str:
    from cityusd.zh_simp import to_simplified

    for key in ("name:zh-Hans", "name:zh", "name", "name:zh-Hant", "name:zh-TW", "name:en", "ref"):
        value = (tags.get(key) or "").strip()
        if value:
            return to_simplified(value)
    return ""


def sign_placements(ways: list[OsmWay], spacing_m: float = 160.0) -> list[dict]:
    """Named major highways: samples along line, offset to the right by width/2+0.6m."""
    placements: list[dict] = []
    if not ways or spacing_m <= 0:
        return placements
    for way in ways:
        if not is_major_highway(way.tags):
            continue
        name = way_display_name(way.tags)
        if not name:
            continue
        if way.coords_m is None or len(way.coords_m) < 2:
            continue
        line = LineString(way.coords_m)
        if line.is_empty or line.length <= 0:
            continue
        width = way_width_m(way.tags)
        lateral = width / 2.0 + SIGN_LATERAL_EXTRA_M
        for dist in _sample_distances(line.length, spacing_m):
            xy, yaw = _point_and_yaw(line, dist)
            if xy is None:
                continue
            dx, dy = math.cos(yaw), math.sin(yaw)
            rx, ry = xy[0] + dy * lateral, xy[1] - dx * lateral
            placements.append({"xy": (rx, ry), "yaw_rad": yaw, "name": name})
    return placements


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _road_rank(tags: dict[str, str]) -> int:
    hwy = tags.get("highway", "")
    try:
        return ROAD_RANK.index(hwy)
    except ValueError:
        return len(ROAD_RANK)


def _coords_from_geom(geom) -> list[tuple[float, float]]:
    if geom is None or geom.is_empty:
        return []
    poly = None
    geom_type = getattr(geom, "geom_type", "")
    if geom_type == "Polygon":
        poly = geom
    elif geom_type == "MultiPolygon" and len(geom.geoms) > 0:
        poly = max(geom.geoms, key=lambda g: g.area)
    if poly is None:
        return []
    return [(float(x), float(y)) for x, y in poly.exterior.coords]


def _parallel_offset(line: LineString, distance: float, side: str):
    if line is None or line.is_empty or distance == 0:
        return line
    try:
        return line.parallel_offset(distance, side)
    except Exception:
        sign = 1.0 if side == "left" else -1.0
        try:
            return line.offset_curve(sign * distance)
        except Exception:
            return line


def _iter_lines(geom):
    if geom is None or getattr(geom, "is_empty", True):
        return
    geom_type = getattr(geom, "geom_type", "")
    if geom_type == "LineString":
        yield geom
        return
    if geom_type in ("MultiLineString", "GeometryCollection"):
        for part in geom.geoms:
            yield from _iter_lines(part)


def _buffer_solid(line, role: str, style: str) -> list[dict]:
    if line is None or getattr(line, "is_empty", True):
        return []
    try:
        poly = line.buffer(MARKING_BUFFER_M)
    except Exception:
        return []
    if poly is None or poly.is_empty:
        return []
    return [{"role": role, "style": style, "geom": poly, "z_m": MARKING_Z_M}]


def _dash_buffers(line, role: str, style: str) -> list[dict]:
    length = float(line.length)
    if length < 0.4:
        return []
    out: list[dict] = []
    start = 0.0
    while start < length:
        end = min(start + DASH_ON_M, length)
        if end - start >= 0.4:
            try:
                seg = substring(line, start, end)
            except Exception:
                seg = None
            if seg is not None and not getattr(seg, "is_empty", True):
                out.extend(_buffer_solid(seg, role, style))
        start += DASH_ON_M + DASH_GAP_M
    return out


def _buffer_marking(line, role: str, style: str) -> list[dict]:
    if line is None or getattr(line, "is_empty", True):
        return []
    if "dash" in style:
        out: list[dict] = []
        for part in _iter_lines(line):
            out.extend(_dash_buffers(part, role, style))
        return out
    return _buffer_solid(line, role, style)


def _node_key(xy) -> tuple[float, float]:
    return (round(float(xy[0]), 3), round(float(xy[1]), 3))


def _degree_at(graph_degree: dict, xy) -> int:
    if xy in graph_degree:
        return int(graph_degree[xy])
    key = _node_key(xy)
    if key in graph_degree:
        return int(graph_degree[key])
    for node, deg in graph_degree.items():
        try:
            if abs(float(node[0]) - float(xy[0])) < 1e-3 and abs(float(node[1]) - float(xy[1])) < 1e-3:
                return int(deg)
        except (TypeError, IndexError):
            continue
    return 0


def _walk_along(coords: list[tuple[float, float]], start: int, step: int, distance: float):
    remaining = distance
    x, y = float(coords[start][0]), float(coords[start][1])
    i = start
    n = len(coords)
    tx = ty = 0.0
    moved = False
    while remaining > 0:
        nxt = i + step
        if nxt < 0 or nxt >= n:
            return None
        x2, y2 = float(coords[nxt][0]), float(coords[nxt][1])
        seg = math.hypot(x2 - x, y2 - y)
        if seg < 1e-12:
            i = nxt
            continue
        ux, uy = (x2 - x) / seg, (y2 - y) / seg
        tx, ty = ux, uy
        moved = True
        if seg >= remaining:
            t = remaining / seg
            return (x + (x2 - x) * t, y + (y2 - y) * t), (-tx, -ty)
        remaining -= seg
        x, y = x2, y2
        i = nxt
    if not moved:
        return None
    return (x, y), (-tx, -ty)


def _arrow_on_approach(coords, node_i: int, step: int, offset_m: float, setback_m: float = ARROW_SETBACK_M):
    walked = _walk_along(coords, node_i, step, float(setback_m))
    if walked is None:
        return None
    (px, py), (ux, uy) = walked
    length = math.hypot(ux, uy)
    if length < 1e-9:
        return None
    ux, uy = ux / length, uy / length
    # Positive offset is to the right of travel (RH inbound lanes).
    px += uy * float(offset_m)
    py -= ux * float(offset_m)
    yaw = math.atan2(uy, ux)
    poly = _chevron_arrow_poly(px, py, ux, uy)
    if poly is None:
        return None
    return poly, (px, py), yaw


def _chevron_arrow_poly(px: float, py: float, ux: float, uy: float):
    """Stem + triangular head, pointing along (ux, uy)."""
    rx, ry = -uy, ux
    half_l = ARROW_LENGTH_M / 2.0
    half_w = ARROW_WIDTH_M / 2.0
    head_len = ARROW_LENGTH_M * 0.42
    stem_w = ARROW_WIDTH_M * 0.34
    tip = (px + ux * half_l, py + uy * half_l)
    head_back = half_l - head_len
    hl = (px + ux * head_back + rx * half_w, py + uy * head_back + ry * half_w)
    hr = (px + ux * head_back - rx * half_w, py + uy * head_back - ry * half_w)
    sl = (px + ux * head_back + rx * (stem_w * 0.5), py + uy * head_back + ry * (stem_w * 0.5))
    sr = (px + ux * head_back - rx * (stem_w * 0.5), py + uy * head_back - ry * (stem_w * 0.5))
    bl = (px - ux * half_l + rx * (stem_w * 0.5), py - uy * half_l + ry * (stem_w * 0.5))
    br = (px - ux * half_l - rx * (stem_w * 0.5), py - uy * half_l - ry * (stem_w * 0.5))
    poly = Polygon([tip, hr, sr, br, bl, sl, hl])
    if poly.is_empty or not poly.is_valid or poly.area < 0.5:
        poly = poly.buffer(0) if not poly.is_empty else poly
    if poly is None or poly.is_empty or not getattr(poly, "is_valid", False):
        return None
    return poly


def _sample_distances(length: float, spacing_m: float) -> Iterable[float]:
    if length <= spacing_m:
        return [length * 0.5]
    distances = []
    d = spacing_m
    while d < length:
        distances.append(d)
        d += spacing_m
    return distances


def _point_and_yaw(line: LineString, dist: float):
    if dist < 0 or dist > line.length:
        if dist > line.length:
            dist = line.length
        elif dist < 0:
            dist = 0.0
    pt = line.interpolate(dist)
    delta = min(0.5, max(line.length * 0.01, 1e-3))
    a = line.interpolate(max(0.0, dist - delta))
    b = line.interpolate(min(line.length, dist + delta))
    dx, dy = b.x - a.x, b.y - a.y
    if math.hypot(dx, dy) < 1e-12:
        return None, None
    yaw = math.atan2(dy, dx)
    return (float(pt.x), float(pt.y)), yaw
