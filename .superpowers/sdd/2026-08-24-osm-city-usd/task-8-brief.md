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

