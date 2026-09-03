from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from cityusd.crs import extent_from_lonlat_bbox, make_origin
from cityusd.types import Origin

try:
    import rasterio
except ImportError:  # pragma: no cover
    rasterio = None


class BoxRelation(str, Enum):
    EQUAL = "equal"
    CONTAINMENT = "containment"
    PARTIAL_OVERLAP = "partial_overlap"
    DISJOINT = "disjoint"
    SINGLE = "single"


@dataclass(frozen=True)
class Wgs84Box:
    lon_west: float
    lat_south: float
    lon_east: float
    lat_north: float

    def as_dict(self) -> dict[str, float]:
        return {
            "lon_west": self.lon_west,
            "lat_south": self.lat_south,
            "lon_east": self.lon_east,
            "lat_north": self.lat_north,
        }

    def pad(self, pad_deg: float) -> Wgs84Box:
        if pad_deg <= 0:
            return self
        return Wgs84Box(
            lon_west=self.lon_west - pad_deg,
            lat_south=self.lat_south - pad_deg,
            lon_east=self.lon_east + pad_deg,
            lat_north=self.lat_north + pad_deg,
        )

    def intersection(self, other: Wgs84Box) -> Optional[Wgs84Box]:
        west = max(self.lon_west, other.lon_west)
        south = max(self.lat_south, other.lat_south)
        east = min(self.lon_east, other.lon_east)
        north = min(self.lat_north, other.lat_north)
        if east <= west or north <= south:
            return None
        return Wgs84Box(west, south, east, north)

    def contains(self, other: Wgs84Box, tol: float = 1e-9) -> bool:
        return (
            other.lon_west >= self.lon_west - tol
            and other.lon_east <= self.lon_east + tol
            and other.lat_south >= self.lat_south - tol
            and other.lat_north <= self.lat_north + tol
        )

    def area_deg2(self) -> float:
        return max(0.0, self.lon_east - self.lon_west) * max(0.0, self.lat_north - self.lat_south)


def _relation(a: Wgs84Box, b: Wgs84Box, area_tol_ratio: float = 0.001) -> BoxRelation:
    inter = a.intersection(b)
    if inter is None:
        return BoxRelation.DISJOINT
    ia = inter.area_deg2()
    aa, ab = a.area_deg2(), b.area_deg2()
    if aa <= 0 or ab <= 0:
        return BoxRelation.DISJOINT
    if abs(ia - aa) / aa < area_tol_ratio and abs(ia - ab) / ab < area_tol_ratio:
        return BoxRelation.EQUAL
    if a.contains(b):
        return BoxRelation.CONTAINMENT
    if b.contains(a):
        return BoxRelation.CONTAINMENT
    return BoxRelation.PARTIAL_OVERLAP


def _relation_label(a: Wgs84Box, b: Wgs84Box, rel: BoxRelation) -> str:
    if rel == BoxRelation.DISJOINT:
        return "disjoint"
    if rel == BoxRelation.PARTIAL_OVERLAP:
        return "partial_overlap"
    if rel == BoxRelation.EQUAL:
        return "equal"
    if a.contains(b):
        return "osm_contains_grid" if a.area_deg2() >= b.area_deg2() else "grid_contains_osm"
    if b.contains(a):
        return "grid_contains_osm" if b.area_deg2() >= a.area_deg2() else "osm_contains_grid"
    return "containment"


def read_raster_bounds_wgs84(path: Path) -> Wgs84Box:
    if rasterio is None:
        raise ImportError("rasterio required for DEM/ortho bounds")
    with rasterio.open(path) as src:
        b = src.bounds
        if src.crs and str(src.crs) != "EPSG:4326":
            from pyproj import Transformer

            fwd = Transformer.from_crs(str(src.crs), "EPSG:4326", always_xy=True)
            corners = [
                fwd.transform(b.left, b.bottom),
                fwd.transform(b.right, b.bottom),
                fwd.transform(b.left, b.top),
                fwd.transform(b.right, b.top),
            ]
            lons = [c[0] for c in corners]
            lats = [c[1] for c in corners]
            return Wgs84Box(min(lons), min(lats), max(lons), max(lats))
        return Wgs84Box(float(b.left), float(b.bottom), float(b.right), float(b.top))


def read_osm_bounds_wgs84(path: Path) -> Wgs84Box:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    name = path.name.lower()
    if name.endswith(".osm") and not name.endswith(".pbf"):
        root = ET.parse(path).root
        bounds = root.find("bounds")
        if bounds is not None:
            return Wgs84Box(
                float(bounds.attrib["minlon"]),
                float(bounds.attrib["minlat"]),
                float(bounds.attrib["maxlon"]),
                float(bounds.attrib["maxlat"]),
            )
        raise ValueError(f"OSM XML missing <bounds>: {path}")
    return _read_pbf_bounds(path)


def _read_pbf_bounds(path: Path) -> Wgs84Box:
    import osmium

    reader = osmium.io.Reader(str(path))
    try:
        header = reader.header()
        if hasattr(header, "has_bbox") and header.has_bbox():
            b = header.get_bbox()
            return Wgs84Box(b.bottom_left.lon, b.bottom_left.lat, b.top_right.lon, b.top_right.lat)
        b = header.box()
        if b is not None and b.valid():
            return Wgs84Box(b.bottom_left.lon, b.bottom_left.lat, b.top_right.lon, b.top_right.lat)
    finally:
        reader.close()

    try:
        return _read_pbf_bounds_pyrosm(path)
    except ImportError:
        pass
    except Exception:
        pass

    lons: list[float] = []
    lats: list[float] = []

    class Scan(osmium.SimpleHandler):
        def node(self, n: osmium.osm.Node) -> None:
            if n.location.valid():
                lons.append(n.location.lon)
                lats.append(n.location.lat)

    Scan().apply_file(str(path), locations=True)
    if not lons:
        raise ValueError(f"No nodes in PBF: {path}")
    return Wgs84Box(min(lons), min(lats), max(lons), max(lats))


def _read_pbf_bounds_pyrosm(path: Path) -> Wgs84Box:
    from pyrosm import OSM

    osm = OSM(str(path))
    for getter in (
        lambda: osm.get_buildings(),
        lambda: osm.get_network(network_type="driving"),
        lambda: osm.get_landuse(),
    ):
        frame = getter()
        if frame is not None and not frame.empty:
            bb = frame.total_bounds
            return Wgs84Box(float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
    raise ValueError(f"Could not infer bounds from PBF: {path}")


def resolve_extent(
    *,
    frame: dict[str, Any],
    inputs: dict[str, Any],
    project_root: Optional[Path] = None,
    input_dirs: Optional[list[Path]] = None,
) -> dict[str, Any]:
    """Compute final WGS84 extent and local meters extent (schema v0.2)."""
    origin_cfg = frame.get("origin_wgs84") or {}
    lon = float(origin_cfg.get("longitude", 0.0))
    lat = float(origin_cfg.get("latitude", 0.0))
    height_m = float(origin_cfg.get("height_m", origin_cfg.get("height", 0.0)))
    utm_epsg = frame.get("utm_epsg")
    origin = make_origin(lon, lat, height_m)
    if utm_epsg is not None:
        origin = Origin(lon=origin.lon, lat=origin.lat, height_m=origin.height_m, epsg=int(utm_epsg))

    extent_cfg = frame.get("extent") or {}
    mode = str(extent_cfg.get("mode") or "auto").lower()
    pad_deg = float(extent_cfg.get("pad_deg", 0.0))
    on_rel = extent_cfg.get("on_relation") or {}
    disjoint_action = str(on_rel.get("disjoint", "fail")).lower()
    partial_action = str(on_rel.get("partial_overlap", "warn")).lower()
    allow_disjoint = bool(extent_cfg.get("allow_disjoint", False))

    warnings: list[str] = []
    errors: list[str] = []
    sources: dict[str, Any] = {}

    osm_in = inputs.get("osm") or {}
    dem_in = inputs.get("dem") or {}
    ortho_in = inputs.get("ortho") or {}

    search_roots: list[Path] = []
    if input_dirs:
        search_roots.extend(Path(p) for p in input_dirs)
    if project_root is not None:
        search_roots.append(Path(project_root))

    def _resolve_input_path(raw: Optional[str]) -> Optional[Path]:
        if not raw:
            return None
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p if p.is_file() else p
        for root in search_roots:
            for cand in ((root / p).resolve(), (root / p.name).resolve()):
                if cand.is_file():
                    return cand
        return (search_roots[0] / p).resolve() if search_roots else p

    osm_path = _resolve_input_path(osm_in.get("path"))
    dem_path = _resolve_input_path(dem_in.get("path"))
    ortho_path = _resolve_input_path(ortho_in.get("path"))
    dem_optional = bool(dem_in.get("optional", False))
    ortho_optional = bool(ortho_in.get("optional", True))

    final: Optional[Wgs84Box] = None
    resolution_strategy = "explicit"
    osm_vs_terrain = "n/a"

    if mode == "explicit":
        ex = extent_cfg.get("explicit") or {}
        final = Wgs84Box(
            float(ex["lon_west"]),
            float(ex["lat_south"]),
            float(ex["lon_east"]),
            float(ex["lat_north"]),
        )
        resolution_strategy = "explicit"
    else:
        osm_box: Optional[Wgs84Box] = None
        grid_box: Optional[Wgs84Box] = None

        if osm_path and osm_path.is_file():
            osm_box = read_osm_bounds_wgs84(osm_path)
            sources["osm"] = {"path": str(osm_path), "wgs84": osm_box.as_dict()}

        dem_box: Optional[Wgs84Box] = None
        ortho_box: Optional[Wgs84Box] = None
        if dem_path and dem_path.is_file():
            dem_box = read_raster_bounds_wgs84(dem_path)
            sources["dem"] = {"path": str(dem_path), "wgs84": dem_box.as_dict()}
        elif dem_path and not dem_optional:
            raise FileNotFoundError(f"DEM not found: {dem_path}")

        if ortho_path and ortho_path.is_file():
            ortho_box = read_raster_bounds_wgs84(ortho_path)
            sources["ortho"] = {"path": str(ortho_path), "wgs84": ortho_box.as_dict()}
        elif ortho_path and not ortho_optional:
            raise FileNotFoundError(f"Ortho not found: {ortho_path}")

        if dem_box and ortho_box:
            grid_box = dem_box.intersection(ortho_box)
            if grid_box is None:
                msg = "DEM and ortho bounds are disjoint"
                if disjoint_action == "fail" and not allow_disjoint:
                    errors.append(msg)
                else:
                    warnings.append(msg)
                grid_box = None
            else:
                resolution_strategy = "intersection(dem,ortho)"
        elif dem_box:
            grid_box = dem_box
            resolution_strategy = "dem_bounds"
        elif ortho_box:
            grid_box = ortho_box
            resolution_strategy = "ortho_bounds"

        if mode == "osm_bbox":
            if osm_box is None:
                raise ValueError("osm_bbox mode requires inputs.osm.path")
            final = osm_box
            resolution_strategy = "osm_bbox"
        elif mode == "dem_bounds":
            if grid_box is None:
                raise ValueError("dem_bounds mode requires DEM (and overlapping ortho if provided)")
            final = grid_box
        elif mode == "auto":
            if grid_box is not None and osm_box is not None:
                rel = _relation(osm_box, grid_box)
                osm_vs_terrain = _relation_label(osm_box, grid_box, rel)
                inter = osm_box.intersection(grid_box)
                if rel == BoxRelation.DISJOINT or inter is None:
                    msg = f"OSM and terrain bounds are disjoint ({osm_vs_terrain})"
                    if disjoint_action == "fail" and not allow_disjoint:
                        errors.append(msg)
                    else:
                        warnings.append(msg)
                    if allow_disjoint:
                        final = osm_box
                        resolution_strategy = "osm_only_allow_disjoint"
                    else:
                        final = None
                elif rel == BoxRelation.PARTIAL_OVERLAP:
                    msg = f"OSM and terrain partially overlap; using intersection ({osm_vs_terrain})"
                    if partial_action == "warn":
                        warnings.append(msg)
                    elif partial_action == "fail":
                        errors.append(msg)
                    final = inter
                    resolution_strategy = "intersection(osm,terrain)"
                else:
                    # containment or equal → smaller area
                    if grid_box.area_deg2() <= osm_box.area_deg2():
                        final = grid_box
                        resolution_strategy = "min_area_grid"
                        if rel == BoxRelation.CONTAINMENT and osm_box.contains(grid_box):
                            osm_vs_terrain = "dem_contained_in_osm"
                    else:
                        final = osm_box
                        resolution_strategy = "min_area_osm"
                        if rel == BoxRelation.CONTAINMENT and grid_box.contains(osm_box):
                            osm_vs_terrain = "osm_contained_in_dem"
                    if rel == BoxRelation.EQUAL:
                        osm_vs_terrain = "equal"
            elif grid_box is not None:
                final = grid_box
            elif osm_box is not None:
                final = osm_box
                resolution_strategy = "osm_bbox"
            else:
                errors.append("auto extent: no OSM or DEM/ortho inputs available")
        else:
            raise ValueError(f"Unknown extent.mode: {mode}")

    if errors:
        raise RuntimeError("resolve_extent failed:\n" + "\n".join(f"  - {e}" for e in errors))
    if final is None:
        raise RuntimeError("resolve_extent: could not determine final extent")

    final = final.pad(pad_deg)
    local = extent_from_lonlat_bbox(
        final.lon_west, final.lat_south, final.lon_east, final.lat_north, origin
    )

    from cityusd.crs import origin_utm

    e0, n0 = origin_utm(origin.lon, origin.lat, origin.epsg)

    payload = {
        "schema_version": "0.2",
        "source": resolution_strategy,
        "wgs84": final.as_dict(),
        "origin_wgs84": {
            "longitude": origin.lon,
            "latitude": origin.lat,
            "height_m": origin.height_m,
        },
        "utm_epsg": origin.epsg,
        "utm_abs_m": {"e0": e0, "n0": n0},
        "local_m": {
            "width_x": local.east - local.west,
            "height_y": local.north - local.south,
            "min_x_m": local.west,
            "max_x_m": local.east,
            "min_y_m": local.south,
            "max_y_m": local.north,
        },
        "sources": sources,
        "resolution": {
            "strategy": resolution_strategy,
            "osm_vs_terrain": osm_vs_terrain,
        },
        "warnings": warnings,
        "errors": errors,
    }
    return payload


def write_extent_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
