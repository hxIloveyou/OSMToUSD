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

