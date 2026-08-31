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

