# OSM City Scene Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Python pipeline under `CityUsd/` that turns OSM (+ optional DEM/imagery/assets) into a UE-ready Scene Package with LOD, Chinese road markings, PGM, and aligned 16-bit heightmap/ortho.

**Architecture:** A small `cityusd` package: scan inputs → shared CRS/extent → rasters + OSM features → shapely overlap/markings → USD layers + PointInstancers → `World_*.usda` + `meta.json` + `nav/map.pgm`. No DEM drape; buildings/roads at Z=0. Description JSON is recorded but not instanced.

**Tech Stack:** Python 3.10+, numpy, shapely, mapbox-earcut, osmium, rasterio, pyproj, Pillow, usd-core (`pxr`)

## Global Constraints

- Work only inside `E:/UEWork/ROS2Test/CityUsd/` (and its `data/` / `output/` / `tools/` / `tests/`).
- `metersPerUnit = 0.01`, `upAxis = Z`, +X east +Y north +Z up.
- Buildings/roads/water/vegetation sit at Z=0 plus spec layer offsets (water -0.02 m, vegetation +0.05 m, roads +0.08 m, buildings +0.04 m); no DEM drape.
- Do not call USDManager or other out-of-tree scripts at runtime.
- Do not instance description-JSON placements; write empty overlay layers.
- Entry file must be `World_<scene_id>.usda` with `defaultPrim = World`; never ship a lone `.usdc`.
- PGM values: occupied=0, free=254, unknown=205; YAML origin is southwest corner in **meters**.
- Heightmap longest side 2049 px; PGM default resolution 1.0 m/px; ortho longest side default 8192 (min 4096).
- Building LOD child mesh names are exactly `LOD0`, `LOD1`, `LOD2`.
- Trees and lamps use `UsdGeomPointInstancer` (UE HISM); placeholder prototypes only.
- If the workspace has no git repo, skip every Commit step.
- Spec: `CityUsd/docs/superpowers/specs/2026-08-24-osm-city-usd-design.md`

## File map

| File | Responsibility |
|------|----------------|
| `tools/requirements.txt` | Pinned runtime deps |
| `tools/cityusd/crs.py` | UTM EPSG, origin, lon/lat ↔ local meters |
| `tools/cityusd/scan_inputs.py` | Find OSM/DEM/imagery/assets/descriptions |
| `tools/cityusd/osm_parse.py` | Parse `.osm` / `.pbf` into typed features |
| `tools/cityusd/rasters.py` | 16-bit heightmap + ortho PNG + JSON |
| `tools/cityusd/geom.py` | Triangulate, buffer, difference, layer Z |
| `tools/cityusd/roads.py` | Width, hierarchy cut, GB 5768 markings, arrows, signs |
| `tools/cityusd/buildings.py` | Height, extrude, LOD cells |
| `tools/cityusd/water_veg.py` | Water/vegetation polygons |
| `tools/cityusd/furniture.py` | Tree/lamp instance poses + placeholder mesh verts |
| `tools/cityusd/pgm.py` | Occupancy grid + `map.yaml` |
| `tools/cityusd/usd_write.py` | Materials, meshes, PointInstancer, layers |
| `tools/cityusd/package.py` | World entry, overlay stubs, meta/manifests |
| `tools/build_city_usd.py` | CLI |
| `tests/fixtures/tiny.osm` | 4-node building + named residential way + water |
| `tests/test_*.py` | One module per package file |

Shared types (define in `tools/cityusd/types.py` in Task 1, reuse everywhere):

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

@dataclass(frozen=True)
class Origin:
    lon: float
    lat: float
    height_m: float
    epsg: int  # e.g. 32651

@dataclass(frozen=True)
class ExtentM:
    west: float   # local meters, min X
    south: float  # min Y
    east: float   # max X
    north: float  # max Y

    @property
    def width(self) -> float:
        return self.east - self.west

    @property
    def height(self) -> float:
        return self.north - self.south

@dataclass
class RasterMeta:
    size_px: Tuple[int, int]
    zmin_m: Optional[float]
    zmax_m: Optional[float]
    origin: Origin
    utm_origin: Tuple[float, float]
    extent_m: ExtentM
    meters_per_pixel: Tuple[float, float]
    crs_epsg: int
    range_source: str  # "dem" | "osm_bbox"

LAYER_Z_M = {"water": -0.02, "vegetation": 0.05, "roads": 0.08, "buildings": 0.04}
CM_PER_M = 100.0
```

---

### Task 1: Scaffold, types, CRS

**Files:**
- Create: `tools/requirements.txt`
- Create: `tools/cityusd/__init__.py`
- Create: `tools/cityusd/types.py`
- Create: `tools/cityusd/crs.py`
- Test: `tests/test_crs.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `utm_epsg(lat: float) -> int`
  - `make_origin(lon: float, lat: float, height_m: float = 0.0) -> Origin`
  - `lonlat_to_local(lon: float, lat: float, origin: Origin) -> Tuple[float, float]` (east_m, north_m)
  - `local_to_lonlat(x_m: float, y_m: float, origin: Origin) -> Tuple[float, float]`
  - `extent_from_lonlat_bbox(west, south, east, north, origin: Origin) -> ExtentM`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crs.py
from cityusd.crs import lonlat_to_local, local_to_lonlat, make_origin, utm_epsg

def test_taipei_epsg():
    assert utm_epsg(25.04756678) == 32651

def test_origin_is_zero():
    o = make_origin(121.53296235, 25.04756678)
    x, y = lonlat_to_local(o.lon, o.lat, o)
    assert abs(x) < 1e-6 and abs(y) < 1e-6

def test_roundtrip():
    o = make_origin(121.53296235, 25.04756678)
    lon, lat = 121.54, 25.05
    x, y = lonlat_to_local(lon, lat, o)
    lon2, lat2 = local_to_lonlat(x, y, o)
    assert abs(lon - lon2) < 1e-7 and abs(lat - lat2) < 1e-7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:\UEWork\ROS2Test\CityUsd` then `pip install pytest pyproj -q` and set `PYTHONPATH=tools` then `pytest tests/test_crs.py -v`

Expected: FAIL with `ModuleNotFoundError: cityusd`

- [ ] **Step 3: Write minimal implementation**

`tools/requirements.txt`:

```
numpy>=1.24
shapely>=2.0
mapbox-earcut>=1.0
osmium>=3.6
rasterio>=1.3
pyproj>=3.6
Pillow>=10.0
usd-core>=23.11
pytest>=7.0
```

`tools/cityusd/crs.py`: use `pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)`. `utm_epsg(lat)` = `32600 + int((lon-based zone))` — zone from longitude: `int((lon + 180) / 6) + 1`, northern hemisphere `32600+zone`. For `utm_epsg` signature taking only lat, also take lon in `make_origin` and store epsg on Origin. **Change:** `utm_epsg(lon: float, lat: float) -> int` so Taipei 121.53E, 25.04N → 32651.

Update test to `utm_epsg(121.53296235, 25.04756678) == 32651`.

```python
def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180.0) / 6.0) + 1
    return (32700 if lat < 0 else 32600) + zone
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_crs.py -v` with `PYTHONPATH=tools`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/requirements.txt tools/cityusd tests/test_crs.py
git commit -m "feat: add CRS helpers for UTM-local meters"
```

---

### Task 2: Input scanner

**Files:**
- Create: `tools/cityusd/scan_inputs.py`
- Test: `tests/test_scan_inputs.py`

**Interfaces:**
- Consumes: `Path`
- Produces:

```python
@dataclass
class FoundInputs:
    osm: Optional[Path]
    dem: Optional[Path]
    imagery: Optional[Path]
    assets_dir: Optional[Path]
    descriptions: list[Path]

def scan_data_dir(data_dir: Path) -> FoundInputs:
    raise NotImplementedError
```

Rules from spec: prefer first `*.osm.pbf` else first `*.osm`; search `data/osm/` then `data/` root. DEM: largest GeoTIFF in `data/dem/` then root (`*.tif`/`*.tiff`). Imagery: largest `*.tif`/`*.tiff`/`*.png` in `data/imagery/` then root, excluding files already chosen as DEM. Descriptions: `data/descriptions/*.json`. Assets: `data/assets` if the directory exists.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from cityusd.scan_inputs import scan_data_dir

def test_prefers_pbf(tmp_path: Path):
    (tmp_path / "osm").mkdir()
    (tmp_path / "osm" / "a.osm").write_text("<osm/>")
    (tmp_path / "osm" / "b.osm.pbf").write_bytes(b"pbf")
    found = scan_data_dir(tmp_path)
    assert found.osm.name == "b.osm.pbf"

def test_missing_osm(tmp_path: Path):
    found = scan_data_dir(tmp_path)
    assert found.osm is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan_inputs.py -v`

Expected: FAIL import error

- [ ] **Step 3: Write minimal implementation** using `rglob` limited to `data_dir` and the named subfolders (do not recurse into unrelated trees).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scan_inputs.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/scan_inputs.py tests/test_scan_inputs.py
git commit -m "feat: scan CityUsd/data for OSM DEM imagery"
```

---

### Task 3: OSM parser

**Files:**
- Create: `tools/cityusd/osm_parse.py`
- Create: `tests/fixtures/tiny.osm`
- Test: `tests/test_osm_parse.py`

**Interfaces:**
- Consumes: `Origin` from `crs.make_origin`
- Produces:

```python
@dataclass
class OsmWay:
    osm_id: int
    tags: dict[str, str]
    coords_m: list[tuple[float, float]]  # local east,north; closed rings repeat first point
    closed: bool

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
```

Classify later; parser only returns ways/nodes with tags. `.osm` via `xml.etree.ElementTree`. `.osm.pbf` via `osmium` (`osmium.SimpleHandler`). Convert lon/lat with `lonlat_to_local`.

`tests/fixtures/tiny.osm` (origin ~119,36 for easy numbers):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lat="36.0000" lon="119.0000"/>
  <node id="2" lat="36.0000" lon="119.0008"/>
  <node id="3" lat="36.0006" lon="119.0008"/>
  <node id="4" lat="36.0006" lon="119.0000"/>
  <node id="5" lat="36.0002" lon="119.0000"/>
  <node id="6" lat="36.0002" lon="119.0008"/>
  <node id="7" lat="36.0007" lon="119.0002"/>
  <node id="8" lat="36.0009" lon="119.0002"/>
  <node id="9" lat="36.0009" lon="119.0005"/>
  <node id="10" lat="36.0007" lon="119.0005"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
    <tag k="building" v="yes"/>
    <tag k="building:levels" v="3"/>
  </way>
  <way id="20">
    <nd ref="5"/><nd ref="6"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="测试路"/>
  </way>
  <way id="30">
    <nd ref="7"/><nd ref="8"/><nd ref="9"/><nd ref="10"/><nd ref="7"/>
    <tag k="natural" v="water"/>
  </way>
  <node id="40" lat="36.0003" lon="119.0004">
    <tag k="natural" v="tree"/>
  </node>
</osm>
```

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from cityusd.osm_parse import parse_osm

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.osm"

def test_parse_tiny_counts():
    data = parse_osm(FIXTURE)
    buildings = [w for w in data.ways if "building" in w.tags]
    roads = [w for w in data.ways if w.tags.get("highway")]
    trees = [n for n in data.nodes if n.tags.get("natural") == "tree"]
    assert len(buildings) == 1 and buildings[0].closed
    assert len(roads) == 1 and roads[0].tags["name"] == "测试路"
    assert len(trees) == 1
    assert data.origin.epsg == 32650  # lon 119 → zone 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_osm_parse.py -v`

Expected: FAIL import

- [ ] **Step 3: Write parser** (XML first; PBF handler mirroring the same `OsmWay`/`OsmNode` construction). Skip ways with fewer than 2 nodes.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_osm_parse.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/osm_parse.py tests/fixtures/tiny.osm tests/test_osm_parse.py
git commit -m "feat: parse OSM XML and PBF into local-meter features"
```

---

### Task 4: DEM heightmap and ortho

**Files:**
- Create: `tools/cityusd/rasters.py`
- Test: `tests/test_rasters.py`

**Interfaces:**
- Consumes: `Origin`, `ExtentM`
- Produces:

```python
def write_heightmap(
    dem_path: Path, origin: Origin, extent: ExtentM, out_png: Path, out_json: Path
) -> RasterMeta:
    raise NotImplementedError

def write_ortho(
    imagery_path: Path, origin: Origin, extent: ExtentM, out_png: Path, out_json: Path,
    max_dim: int = 8192,
) -> RasterMeta:
    raise NotImplementedError
```

Heightmap: reproject DEM to `EPSG:{origin.epsg}`, crop to UTM rectangle corresponding to `extent` (convert local extent to absolute UTM via `utm_origin + local`). Resize longest side to 2049 (keep aspect, both dimensions odd if possible). 16-bit PNG. North-up. JSON keys exactly: `size_px`, `zmin_m`, `zmax_m`, `origin_wgs84`, `utm_origin`, `extent_m` (`east`/`north` widths plus `west/south/east/north` local), `meters_per_pixel`, `crs_epsg`.

`meters_per_pixel = (extent.width / (size_px[0]-1), extent.height / (size_px[1]-1))`.

Ortho: same rectangle; longest side `max(4096, min(max_dim, 8192))` default 8192; 8-bit RGB PNG; same extent JSON without zmin/zmax (set them null).

- [ ] **Step 1: Write the failing test**

```python
import json
import numpy as np
import rasterio
from rasterio.transform import from_origin
from cityusd.crs import make_origin, extent_from_lonlat_bbox
from cityusd.rasters import write_heightmap

def test_heightmap_written(tmp_path):
    tif = tmp_path / "dem.tif"
    arr = np.linspace(10.0, 40.0, 32 * 32, dtype=np.float32).reshape(32, 32)
    transform = from_origin(118.999, 36.002, 0.0001, 0.0001)
    with rasterio.open(
        tif, "w", driver="GTiff", height=32, width=32, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(arr, 1)
    origin = make_origin(119.0006, 36.0004)
    extent = extent_from_lonlat_bbox(118.999, 35.9988, 119.0022, 36.002, origin)
    meta = write_heightmap(tif, origin, extent, tmp_path / "h.png", tmp_path / "h.json")
    assert meta.size_px[0] <= 2049 and meta.size_px[1] <= 2049
    assert meta.zmin_m < meta.zmax_m
    assert (tmp_path / "h.png").exists()
    payload = json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))
    assert payload["crs_epsg"] == origin.epsg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rasters.py::test_heightmap_written -v`

Expected: FAIL import

- [ ] **Step 3: Implement `write_heightmap` / `write_ortho`** with `rasterio.warp.reproject` and `PIL.Image` mode `I;16` for heightmap.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rasters.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/rasters.py tests/test_rasters.py
git commit -m "feat: export aligned 16-bit heightmap and ortho PNG"
```

---

### Task 5: Geometry helpers

**Files:**
- Create: `tools/cityusd/geom.py`
- Test: `tests/test_geom.py`

**Interfaces:**
- Consumes: shapely polygons, `LAYER_Z_M`, `CM_PER_M`
- Produces:

```python
def triangulate_polygon(poly) -> tuple[list[tuple[float,float]], list[tuple[int,int,int]]]:
    """Return 2D verts + triangle indices via mapbox_earcut. Empty if invalid."""

def to_mesh_cm(
    verts_m: list[tuple[float,float]],
    faces: list[tuple[int,int,int]],
    z_m: float,
) -> tuple[list[tuple[float,float,float]], list[int]]:
    """XYZ centimeters; face indices flattened later in USD writer."""

def difference_safe(geom, cutter):
    """geom.difference(cutter) with empty/invalid fallback to original."""
```

- [ ] **Step 1: Write the failing test**

```python
from shapely.geometry import Polygon
from cityusd.geom import triangulate_polygon, to_mesh_cm

def test_unit_square_two_tris():
    verts, faces = triangulate_polygon(Polygon([(0,0),(10,0),(10,10),(0,10)]))
    assert len(faces) >= 2
    pts, _ = to_mesh_cm(verts, faces, z_m=0.08)
    assert all(abs(p[2] - 8.0) < 1e-6 for p in pts)  # 0.08m → 8cm
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_geom.py -v`

Expected: FAIL import

- [ ] **Step 3: Implement earcut triangulation** (`earcut.triangulate_float64` with ring counts). Skip polygons with area &lt; 0.05 m².

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_geom.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/geom.py tests/test_geom.py
git commit -m "feat: triangulate polygons to centimeter meshes"
```

---

### Task 6: Roads — width, overlap, GB 5768 markings, arrows, signs

**Files:**
- Create: `tools/cityusd/roads.py`
- Test: `tests/test_roads.py`

**Interfaces:**
- Consumes: `list[OsmWay]`, shapely
- Produces:

```python
ROAD_WIDTH_M = {
    "motorway": 22.0, "trunk": 16.0, "primary": 12.0, "secondary": 9.0,
    "tertiary": 7.0, "residential": 6.0, "service": 4.0, "footway": 2.0,
    "path": 2.0, "default": 5.0,
}
ROAD_RANK = ["motorway","trunk","primary","secondary","tertiary","residential","service","footway","path"]

def way_width_m(tags: dict[str, str]) -> float:
    raise NotImplementedError

def is_motor_highway(tags: dict[str, str]) -> bool:
    """True if highway set and not footway/path/steps/pedestrian."""

def build_road_polygons(ways: list[OsmWay]) -> list[tuple[OsmWay, object]]:
    """LineString buffer by half-width; skip <2 coords."""

def subtract_road_hierarchy(buffered: list[tuple[OsmWay, object]]) -> list[tuple[OsmWay, object]]:
    """Higher rank cuts lower rank (spec §6.4.1). Junction: unary_union of overlaps as extra 'junction' poly with tag highway=junction."""

def marking_kind(tags: dict[str, str], width_m: float) -> dict:
    """Return {center: 'double_yellow_solid'|'single_yellow_solid'|'single_yellow_dash'|'single_white_dash'|'none', lane: 'white_dash'|'none', edge: 'white_solid'|'none'} per spec table."""

def offset_polylines(coords_m, width_m) -> dict:
    """Centerline plus left/right edge lines for marking meshes (shapely parallel_offset)."""

def junction_arrows(buffered, graph_degree: dict) -> list:
    """For nodes with degree>=3, place a 2.5m arrow poly on each approach 8m before the node, pointing into junction."""

def sign_placements(ways: list[OsmWay], spacing_m: float = 100.0) -> list[dict]:
    """For motor highways with name/name:zh/name:en, samples along line at spacing, offset to the right by width/2+0.6m. Each dict: {xy, yaw_rad, name}."""
```

`way_width_m`: parse `width` as float if present; else `lanes * 3.5`; else table; unknown highway → 5.0.

`marking_kind` exact table:

- motorway/trunk: center double_yellow_solid, lane white_dash, edge white_solid
- primary: same
- secondary: center double_yellow_solid if width_m >= 9 else single_yellow_solid; lane white_dash; edge white_solid
- tertiary: center single_yellow_dash; lane none unless width_m >= 8 then white_dash; edge none
- residential: center single_white_dash if width_m >= 6 else none
- else: all none

- [ ] **Step 1: Write the failing test**

```python
from cityusd.roads import way_width_m, marking_kind, is_motor_highway

def test_width_lanes_override():
    assert way_width_m({"highway": "residential", "lanes": "2"}) == 7.0

def test_primary_double_yellow():
    k = marking_kind({"highway": "primary"}, 12.0)
    assert k["center"] == "double_yellow_solid"

def test_footway_not_motor():
    assert is_motor_highway({"highway": "footway"}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_roads.py -v`

Expected: FAIL import

- [ ] **Step 3: Implement width, markings, buffer, hierarchy difference, arrow and sign placement.** Marking meshes: thin `LineString.buffer(0.08)` at z = roads+0.01 m. Arrows: triangle polygon 2.0×0.8 m. Do not use a two-way opposing-arrow texture.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_roads.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/roads.py tests/test_roads.py
git commit -m "feat: road widths GB5768 markings arrows and signs"
```

---

### Task 7: Buildings with LOD cells

**Files:**
- Create: `tools/cityusd/buildings.py`
- Test: `tests/test_buildings.py`

**Interfaces:**
- Consumes: `OsmWay`, `difference_safe`, road union polygon
- Produces:

```python
def building_height_m(tags: dict[str, str]) -> float:
    """height tag → else levels*3.0 → else 10.0"""

def footprint_after_roads(way: OsmWay, roads_union) -> object:
    """Polygon difference; skip if empty."""

def lod_cell_key(x_m: float, y_m: float, cell_m: float) -> tuple[int, int]:
    return (math.floor(x_m / cell_m), math.floor(y_m / cell_m))

def group_buildings_for_lod(items: list, cell_m: float) -> dict[tuple[int,int], list]:
    """Group by footprint centroid."""

LOD_LEVELS = [
    {"name": "LOD0", "cell_size_m": 200.0, "switch_distance_m": 0.0, "merge_materials": False},
    {"name": "LOD1", "cell_size_m": 800.0, "switch_distance_m": 1500.0, "merge_materials": False},
    {"name": "LOD2", "cell_size_m": 3200.0, "switch_distance_m": 6000.0, "merge_materials": True},
]
```

Extrusion happens in the USD writer: footprint triangles at z_bottom and z_top plus walls. This task returns footprints + height + osm_id + cell keys for each LOD.

- [ ] **Step 1: Write the failing test**

```python
from cityusd.buildings import building_height_m, lod_cell_key

def test_levels():
    assert building_height_m({"building": "yes", "building:levels": "3"}) == 9.0

def test_default_10():
    assert building_height_m({"building": "yes"}) == 10.0

def test_cell():
    assert lod_cell_key(250.0, 50.0, 200.0) == (1, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_buildings.py -v`

Expected: FAIL import

- [ ] **Step 3: Implement height parsing (`re` for `12 m` / `12m`) and grouping.**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_buildings.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/buildings.py tests/test_buildings.py
git commit -m "feat: building height and LOD cell grouping"
```

---

### Task 8: Water, vegetation, furniture instancers

**Files:**
- Create: `tools/cityusd/water_veg.py`
- Create: `tools/cityusd/furniture.py`
- Test: `tests/test_water_veg.py`
- Test: `tests/test_furniture.py`

**Interfaces:**
- Consumes: `OsmData`, road union, building union
- Produces:

```python
WATERWAY_WIDTH_M = {"river": 8.0, "stream": 3.0, "canal": 5.0, "default": 4.0}

def water_polygons(data: OsmData, cutters) -> list:
def vegetation_polygons(data: OsmData, cutters) -> list:
    """Difference against roads+buildings. Water tags: natural=water, water=*, landuse=reservoir. Vegetation: landuse grass/forest/meadow, leisure=park, natural=wood."""

def tree_instances(data: OsmData) -> list[tuple[float,float,float]]:
    """natural=tree nodes → (x,y,yaw=0)."""

def lamp_instances(motor_ways: list[OsmWay], spacing_m: float = 30.0) -> list[tuple[float,float,float]]:
    """primary/trunk/motorway only; both sides; spacing 25-35 default 30; offset width/2+0.4m."""

def placeholder_tree_mesh() -> tuple[list, list]:  # verts cm, faces
def placeholder_lamp_mesh() -> tuple[list, list]:
```

Tree mesh: cylinder radius 0.15 m height 1.2 m + cone radius 1.2 m height 2.5 m. Lamp: cylinder radius 0.08 m height 6 m + box 0.3³ on top. Coordinates in centimeters, origin at ground center.

- [ ] **Step 1: Write the failing tests**

```python
from cityusd.furniture import lamp_instances, placeholder_tree_mesh
from cityusd.osm_parse import OsmWay

def test_lamp_only_primary():
    res = OsmWay(1, {"highway": "residential"}, [(0.0,0.0),(40.0,0.0)], False)
    pri = OsmWay(2, {"highway": "primary"}, [(0.0,10.0),(60.0,10.0)], False)
    assert lamp_instances([res]) == []
    assert len(lamp_instances([pri])) >= 2

def test_tree_placeholder_has_faces():
    v, f = placeholder_tree_mesh()
    assert len(v) > 8 and len(f) > 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_furniture.py -v`

Expected: FAIL import

- [ ] **Step 3: Implement water_veg + furniture.** On difference failure, skip that feature and increment a module-level `skip_count`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_furniture.py tests/test_water_veg.py -v`

Expected: PASS (`test_water_veg.py` should parse `tiny.osm` water way and return one polygon)

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/water_veg.py tools/cityusd/furniture.py tests/test_furniture.py tests/test_water_veg.py
git commit -m "feat: water vegetation and HISM placeholder instances"
```

---

### Task 9: PGM occupancy

**Files:**
- Create: `tools/cityusd/pgm.py`
- Test: `tests/test_pgm.py`

**Interfaces:**
- Consumes: `ExtentM`, building polygons, water polygons, motor-road polygons
- Produces:

```python
def rasterize_pgm(
    extent: ExtentM,
    occupied_polys: list,
    free_polys: list,
    resolution_m: float,
    out_pgm: Path,
    out_yaml: Path,
    out_json: Path,
    origin: Origin,
    range_source: str,
) -> RasterMeta:
```

Grid: `nx = ceil(extent.width / resolution_m)`, `ny = ceil(extent.height / resolution_m)`. Fill 205, then burn free (254) then occupied (0) so buildings win over roads. Image row 0 = north (`ny-1` local). YAML:

```
image: map.pgm
resolution: <resolution_m>
origin: [<extent.west>, <extent.south>, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
```

`map_meta.json` same fields as heightmap meta plus `range_source`.

- [ ] **Step 1: Write the failing test**

```python
from shapely.geometry import Polygon, box
from cityusd.types import ExtentM
from cityusd.crs import make_origin
from cityusd.pgm import rasterize_pgm

def test_building_is_occupied(tmp_path):
    extent = ExtentM(-50, -50, 50, 50)
    occ = [box(-10, -10, 10, 10)]
    free = [box(-40, -2, 40, 2)]
    o = make_origin(119.0, 36.0)
    meta = rasterize_pgm(extent, occ, free, 1.0, tmp_path/"map.pgm", tmp_path/"map.yaml", tmp_path/"map_meta.json", o, "osm_bbox")
    raw = (tmp_path/"map.pgm").read_bytes()
    assert b"P5" in raw[:8]
    yaml_text = (tmp_path/"map.yaml").read_text(encoding="utf-8")
    assert "origin: [-50.0, -50.0, 0.0]" in yaml_text or "origin: [-50, -50, 0]" in yaml_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pgm.py -v`

Expected: FAIL import

- [ ] **Step 3: Implement with `rasterio.features.rasterize` or shapely + numpy indexing.** Write binary PGM P5, 8-bit.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pgm.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/pgm.py tests/test_pgm.py
git commit -m "feat: write Nav2 PGM aligned to USD extent"
```

---

### Task 10: USD layers, PointInstancer, package metadata

**Files:**
- Create: `tools/cityusd/usd_write.py`
- Create: `tools/cityusd/package.py`
- Test: `tests/test_usd_package.py`

**Interfaces:**
- Consumes: meshes, instance lists, `RasterMeta`, `FoundInputs`, `scene_id`
- Produces:

```python
def write_mesh(stage, path: str, points_cm, face_counts, face_indices, material_path: Optional[str]) -> None:
def write_point_instancer(stage, path: str, proto_prim_path: str, positions_cm, yaws_rad) -> None:
def write_placeholder_prototype(stage, path: str, verts, faces) -> None:
def write_environment_layer(path: Path) -> None:
def write_terrain_layer(path: Path, heightmap_rel: Optional[str], ortho_rel: Optional[str], meta: Optional[RasterMeta]) -> None:
def write_nav_layer(path: Path, pgm_rel: Optional[str], yaml_rel: Optional[str]) -> None:
def write_empty_overlay(path: Path, prim_name: str) -> None:
def write_world(path: Path, scene_id: str, sublayers: list[str]) -> None:
def write_meta(path: Path, payload: dict) -> None:
```

USD details:

- `UsdGeom.SetStageMetersPerUnit(stage, 0.01)` and `SetStageUpAxis(stage, UsdGeom.Tokens.z)`.
- Colors via `UsdShade.Material` UsdPreviewSurface; generate 8×8 PNG stripes for yellow/white markings under `textures/` if no library file.
- Buildings: for each LOD0 cell, prim `/World/City/Buildings/c{ix}_{iy}` with children `LOD0`, `LOD1`, `LOD2` meshes (LOD1/LOD2 may merge many footprints). Set customData `switch_distance_m` on parent.
- Terrain/nav layers: `UsdGeom.Xform` `/World/Terrain` and `/World/Nav` with `customData` keys `heightmap_png`, `ortho_png`, `map_pgm`, `map_yaml` as relative paths. Optional 1×1 hidden reference plane at Z=-1 cm, `visibility=invisible`.
- Overlays: `/World/Overlay/Equipment` etc. empty Xforms.
- World subLayers order exactly as spec §5.
- `meta.json` must include: `spec_version` `"1.0"`, `scene_id`, `crs`, `units.meters_per_unit` 0.01, layer paths, overlay paths, `lod` table, `vegetation_instancer` true, `lamp_instancer` true, `prototype_swap` true, `capabilities.has_building_lod` true.

- [ ] **Step 1: Write the failing test**

```python
from pxr import Usd, UsdGeom
from cityusd.package import write_world, write_empty_overlay
from cityusd.usd_write import write_environment_layer

def test_world_opens(tmp_path):
    env = tmp_path / "layers" / "environment.usda"
    env.parent.mkdir(parents=True)
    write_environment_layer(env)
    ov = tmp_path / "overlay"
    ov.mkdir()
    write_empty_overlay(ov / "equipment.usda", "Equipment")
    world = tmp_path / "World_test.usda"
    write_world(world, "test", [
        "./layers/environment.usda",
        "./overlay/equipment.usda",
    ])
    stage = Usd.Stage.Open(str(world))
    assert stage.GetDefaultPrim().GetName() == "World"
    assert UsdGeom.GetStageMetersPerUnit(stage) == 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_usd_package.py -v`

Expected: FAIL import

- [ ] **Step 3: Implement writers.** Copy prototype meshes into `models/prototypes/tree.usda` and `lamp.usda` referenced by PointInstancer `prototypes` relationship. Positions in centimeters.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_usd_package.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/usd_write.py tools/cityusd/package.py tests/test_usd_package.py
git commit -m "feat: write World layers PointInstancer and meta.json"
```

---

### Task 11: CLI orchestrator and tiny-OSM integration test

**Files:**
- Create: `tools/build_city_usd.py`
- Test: `tests/test_build_cli.py`

**Interfaces:**
- Consumes: all previous modules
- Produces: full Scene Package under `--output`

CLI:

```
python tools/build_city_usd.py --data <dir> --output <dir>
  [--pgm-resolution 1.0] [--ortho-max-dim 8192] [--scene-id ID] [--description PATH]
```

Algorithm:

1. `found = scan_data_dir(data)`
2. If `found.osm is None`: print error, `sys.exit(1)` — write nothing
3. `osm = parse_osm(found.osm)`
4. If DEM: origin = DEM geographic center (raster bounds center lon/lat); extent from DEM rectangle in local m. Else origin = OSM bbox center; extent from OSM bbox (`range_source` `osm_bbox` vs `dem`)
5. Re-parse OSM with that origin if origin changed
6. Write heightmap/ortho if files exist; skip with warning otherwise
7. Build road polygons → hierarchy subtract → markings/arrows/signs
8. Buildings minus roads; water/veg minus roads+buildings
9. PGM from those polygons
10. Write USD city meshes into `layers/base_osm.usdc` (or `.usda` if usdc too heavy for tests — production default `.usdc`)
11. Environment, terrain, nav, five overlay files, World, meta, sources_manifest (include description paths if present; `--description` appends), assets_used
12. `scene_id` default `f"{osm.stem}_{YYYYMMDD}"`

`sources_manifest.json`: `{ "osm": str, "dem": str|null, "imagery": str|null, "descriptions": [str], "asset_library": str|null }`

- [ ] **Step 1: Write the failing integration test**

```python
from pathlib import Path
import json
from pxr import Usd
from build_city_usd import main

def test_tiny_package(tmp_path):
    data = tmp_path / "data"
    (data / "osm").mkdir(parents=True)
    src = Path("tests/fixtures/tiny.osm")
    (data / "osm" / "tiny.osm").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out"
    rc = main(["--data", str(data), "--output", str(out), "--scene-id", "tiny_test"])
    assert rc == 0
    world = next(out.glob("World_*.usda"))
    stage = Usd.Stage.Open(str(world))
    assert stage.GetDefaultPrim().GetName() == "World"
    assert (out / "nav" / "map.pgm").exists()
    assert (out / "nav" / "map.yaml").exists()
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["units"]["meters_per_unit"] == 0.01
    assert (out / "overlay" / "equipment.usda").exists()
    # no DEM → no heightmap file
    assert not (out / "terrain_src" / "heightmap_16bit.png").exists()
```

```python
def test_missing_osm_exits(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    out = tmp_path / "out"
    rc = main(["--data", str(data), "--output", str(out)])
    assert rc != 0
    assert not out.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_build_cli.py -v`

Expected: FAIL import `build_city_usd`

- [ ] **Step 3: Implement `tools/build_city_usd.py`** `def main(argv: Optional[list[str]] = None) -> int` using argparse. Insert `tools/` on `sys.path`. Catch per-feature triangulation errors, count skips, print summary.

- [ ] **Step 4: Run all tests**

Run: `pytest tests -v`

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/build_city_usd.py tests/test_build_cli.py
git commit -m "feat: CLI builds Scene Package from CityUsd/data"
```

---

## Spec coverage (self-review)

| Spec section | Task |
|--------------|------|
| §1 inputs / scan | Task 2 |
| §3 CRS / origin / extent | Task 1, Task 11 step 4 |
| §6.1–6.3 roads, markings, signs | Task 6 |
| §6.4 overlap | Task 6 hierarchy, Task 7 footprints, Task 8 cutters |
| §6.5 buildings LOD names | Task 7 + Task 10 |
| §6.6 water/veg | Task 8 |
| §7 PointInstancer HISM | Task 8 + Task 10 |
| §8 description reserved | Task 11 sources_manifest + empty overlay |
| §9 heightmap/ortho | Task 4 |
| §9.3 PGM | Task 9 |
| §10 assets fallback | Task 10 generated textures/prototypes |
| §11 no OSM fails | Task 11 |
| §12 acceptance | Task 11 integration test |
| §13 CLI flags | Task 11 |

No DEM drape: never sample DEM onto building/road Z (only Task 4 rasters + Task 10 references).
