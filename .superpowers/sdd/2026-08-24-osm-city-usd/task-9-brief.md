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

