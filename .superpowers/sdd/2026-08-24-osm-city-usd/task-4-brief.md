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

