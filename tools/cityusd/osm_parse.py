from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cityusd.crs import lonlat_to_local, make_origin
from cityusd.types import Origin


@dataclass
class OsmWay:
    osm_id: int
    tags: dict[str, str]
    coords_m: list[tuple[float, float]]  # local east,north; closed rings repeat first point
    closed: bool
    vertex_width_m: Optional[list[float]] = None


@dataclass
class OsmNode:
    osm_id: int
    tags: dict[str, str]
    xy_m: tuple[float, float]


@dataclass
class OsmData:
    origin: Origin
    ways: list[OsmWay]
    nodes: list[OsmNode]
    lonlat_bbox: tuple[float, float, float, float]  # west,south,east,north


def parse_osm(path: Path, origin: Optional[Origin] = None) -> OsmData:
    """If origin is None, use bbox center."""
    path = Path(path)
    suffix = path.suffix.lower()
    name = path.name.lower()
    if name.endswith(".osm.pbf") or suffix == ".pbf":
        return _parse_pbf(path, origin)
    return _parse_xml(path, origin)


def _bbox_and_origin(
    lons: list[float],
    lats: list[float],
    origin: Optional[Origin],
) -> tuple[tuple[float, float, float, float], Origin]:
    if not lons or not lats:
        raise ValueError("OSM file contains no nodes")
    west, east = min(lons), max(lons)
    south, north = min(lats), max(lats)
    bbox = (west, south, east, north)
    if origin is None:
        origin = make_origin((west + east) / 2.0, (south + north) / 2.0)
    return bbox, origin


def _build_ways(
    raw_ways: list[tuple[int, dict[str, str], list[tuple[float, float]]]],
    origin: Origin,
) -> list[OsmWay]:
    ways: list[OsmWay] = []
    for osm_id, tags, lonlats in raw_ways:
        if len(lonlats) < 2:
            continue
        if not tags:
            continue
        coords_m = [lonlat_to_local(lon, lat, origin) for lon, lat in lonlats]
        closed = len(coords_m) >= 3 and coords_m[0] == coords_m[-1]
        # Also treat explicit closed ring by lon/lat identity
        if not closed and len(lonlats) >= 3:
            closed = lonlats[0] == lonlats[-1]
        ways.append(OsmWay(osm_id=osm_id, tags=tags, coords_m=coords_m, closed=closed))
    return ways


def _build_nodes(
    raw_nodes: list[tuple[int, dict[str, str], float, float]],
    origin: Origin,
) -> list[OsmNode]:
    nodes: list[OsmNode] = []
    for osm_id, tags, lon, lat in raw_nodes:
        if not tags:
            continue
        xy_m = lonlat_to_local(lon, lat, origin)
        nodes.append(OsmNode(osm_id=osm_id, tags=tags, xy_m=xy_m))
    return nodes


def _parse_xml(path: Path, origin: Optional[Origin]) -> OsmData:
    root = ET.parse(path).getroot()
    node_lonlat: dict[int, tuple[float, float]] = {}
    tagged_nodes: list[tuple[int, dict[str, str], float, float]] = []
    lons: list[float] = []
    lats: list[float] = []

    for el in root.findall("node"):
        osm_id = int(el.attrib["id"])
        lon = float(el.attrib["lon"])
        lat = float(el.attrib["lat"])
        node_lonlat[osm_id] = (lon, lat)
        lons.append(lon)
        lats.append(lat)
        tags = {t.attrib["k"]: t.attrib["v"] for t in el.findall("tag")}
        if tags:
            tagged_nodes.append((osm_id, tags, lon, lat))

    raw_ways: list[tuple[int, dict[str, str], list[tuple[float, float]]]] = []
    for el in root.findall("way"):
        osm_id = int(el.attrib["id"])
        tags = {t.attrib["k"]: t.attrib["v"] for t in el.findall("tag")}
        coords: list[tuple[float, float]] = []
        for nd in el.findall("nd"):
            ref = int(nd.attrib["ref"])
            if ref in node_lonlat:
                coords.append(node_lonlat[ref])
        raw_ways.append((osm_id, tags, coords))

    bbox, origin = _bbox_and_origin(lons, lats, origin)
    return OsmData(
        origin=origin,
        ways=_build_ways(raw_ways, origin),
        nodes=_build_nodes(tagged_nodes, origin),
        lonlat_bbox=bbox,
    )


def _parse_pbf(path: Path, origin: Optional[Origin]) -> OsmData:
    import osmium

    node_lonlat: dict[int, tuple[float, float]] = {}
    tagged_nodes: list[tuple[int, dict[str, str], float, float]] = []
    raw_ways: list[tuple[int, dict[str, str], list[tuple[float, float]]]] = []
    lons: list[float] = []
    lats: list[float] = []

    class Handler(osmium.SimpleHandler):
        def node(self, n: osmium.osm.Node) -> None:
            lon = n.location.lon
            lat = n.location.lat
            node_lonlat[n.id] = (lon, lat)
            lons.append(lon)
            lats.append(lat)
            tags = {t.k: t.v for t in n.tags}
            if tags:
                tagged_nodes.append((n.id, tags, lon, lat))

        def way(self, w: osmium.osm.Way) -> None:
            tags = {t.k: t.v for t in w.tags}
            coords: list[tuple[float, float]] = []
            for nd in w.nodes:
                if nd.location.valid():
                    coords.append((nd.location.lon, nd.location.lat))
                else:
                    loc = node_lonlat.get(nd.ref)
                    if loc is not None:
                        coords.append(loc)
            raw_ways.append((w.id, tags, coords))

    Handler().apply_file(str(path), locations=True)

    bbox, origin = _bbox_and_origin(lons, lats, origin)
    return OsmData(
        origin=origin,
        ways=_build_ways(raw_ways, origin),
        nodes=_build_nodes(tagged_nodes, origin),
        lonlat_bbox=bbox,
    )
