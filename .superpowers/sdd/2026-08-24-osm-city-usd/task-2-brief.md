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

