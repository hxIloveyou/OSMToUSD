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

