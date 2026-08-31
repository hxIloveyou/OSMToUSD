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
