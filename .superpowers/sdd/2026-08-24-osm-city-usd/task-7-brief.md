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

