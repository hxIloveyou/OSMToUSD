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

