"""Crop a 500m x 500m window from the center of taibei.osm.pbf."""

from __future__ import annotations

import sys
from pathlib import Path

import osmium
from pyproj import Transformer

SRC = Path(__file__).with_name("taibei.osm.pbf")
OUT_PBF = Path(__file__).with_name("taibei_center_500m.osm.pbf")
OUT_OSM = Path(__file__).with_name("taibei_center_500m.osm")
HALF_M = 250.0
# Scene origin from presets/taibei_ue.yaml. The PBF lon/lat bbox center
# (approx. 121.615, 25.072) sits in a sparse area with no OSM nodes.
SCENE_CENTER = (121.532933, 25.047453)


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180.0) / 6.0) + 1
    return (32700 if lat < 0 else 32600) + zone


def read_node_bbox(path: Path) -> tuple[float, float, float, float]:
    west = south = float("inf")
    east = north = float("-inf")
    count = 0

    class Scan(osmium.SimpleHandler):
        def node(self, n: osmium.osm.Node) -> None:
            nonlocal west, south, east, north, count
            if not n.location.valid():
                return
            lon, lat = n.location.lon, n.location.lat
            if lon < west:
                west = lon
            if lon > east:
                east = lon
            if lat < south:
                south = lat
            if lat > north:
                north = lat
            count += 1

    Scan().apply_file(str(path), locations=True)
    if count == 0 or west == float("inf"):
        raise RuntimeError(f"No valid nodes in {path}")
    print(f"source nodes={count}")
    print(f"source bbox lon=[{west:.7f}, {east:.7f}] lat=[{south:.7f}, {north:.7f}]")
    return west, south, east, north


def crop_box_wgs84(clon: float, clat: float, half_m: float) -> tuple[float, float, float, float]:
    epsg = utm_epsg(clon, clat)
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_wgs = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    ce, cn = to_utm.transform(clon, clat)
    corners = [
        to_wgs.transform(ce - half_m, cn - half_m),
        to_wgs.transform(ce + half_m, cn - half_m),
        to_wgs.transform(ce - half_m, cn + half_m),
        to_wgs.transform(ce + half_m, cn + half_m),
    ]
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    west, east = min(lons), max(lons)
    south, north = min(lats), max(lats)
    print(f"center lon={clon:.7f} lat={clat:.7f} utm_epsg={epsg}")
    print(f"crop {half_m * 2:.0f}m x {half_m * 2:.0f}m")
    print(f"crop bbox lon=[{west:.7f}, {east:.7f}] lat=[{south:.7f}, {north:.7f}]")
    return west, south, east, north


def collect_ids(path: Path, west: float, south: float, east: float, north: float) -> osmium.IdTracker:
    box = osmium.osm.Box(west, south, east, north)
    ids = osmium.IdTracker()
    inside = 0

    class Collect(osmium.SimpleHandler):
        def node(self, n: osmium.osm.Node) -> None:
            nonlocal inside
            if n.location.valid() and box.contains(n.location):
                ids.add_node(n.id)
                inside += 1

    Collect().apply_file(str(path), locations=True)
    print(f"nodes inside crop box={inside}")
    ids.complete_forward_references(str(path), relation_depth=1)
    ids.complete_backward_references(str(path), relation_depth=1)
    print(
        f"after refs nodes={len(ids.node_ids())} "
        f"ways={len(ids.way_ids())} relations={len(ids.relation_ids())}"
    )
    return ids


def write_outputs(
    path: Path,
    ids: osmium.IdTracker,
    west: float,
    south: float,
    east: float,
    north: float,
) -> None:
    header = osmium.io.Header()
    header.add_box(osmium.osm.Box(west, south, east, north))
    n_node = n_way = n_rel = 0
    with osmium.SimpleWriter(str(OUT_PBF), header=header, overwrite=True) as wpbf, osmium.SimpleWriter(
        str(OUT_OSM), header=header, overwrite=True
    ) as wosm:
        for obj in osmium.FileProcessor(str(path)).with_filter(ids.id_filter()):
            wpbf.add(obj)
            wosm.add(obj)
            if obj.is_node():
                n_node += 1
            elif obj.is_way():
                n_way += 1
            elif obj.is_relation():
                n_rel += 1
    print(f"wrote nodes={n_node} ways={n_way} relations={n_rel}")
    print(f"pbf {OUT_PBF} ({OUT_PBF.stat().st_size} bytes)")
    print(f"osm {OUT_OSM} ({OUT_OSM.stat().st_size} bytes)")


def main() -> int:
    if not SRC.is_file():
        raise FileNotFoundError(SRC)
    west0, south0, east0, north0 = read_node_bbox(SRC)
    bbox_clon = (west0 + east0) / 2.0
    bbox_clat = (south0 + north0) / 2.0
    print(f"bbox geometric center lon={bbox_clon:.7f} lat={bbox_clat:.7f} (unused, empty)")
    clon, clat = SCENE_CENTER
    west, south, east, north = crop_box_wgs84(clon, clat, HALF_M)
    ids = collect_ids(SRC, west, south, east, north)
    if len(ids.node_ids()) == 0:
        raise RuntimeError("Crop box contains no OSM nodes")
    write_outputs(SRC, ids, west, south, east, north)
    return 0


if __name__ == "__main__":
    sys.exit(main())
