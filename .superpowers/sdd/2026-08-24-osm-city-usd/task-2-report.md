# Task 2 Report: Input scanner

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git repo)

## Summary

Implemented `FoundInputs` dataclass and `scan_data_dir()` in `tools/cityusd/scan_inputs.py` with TDD. The scanner locates OSM, DEM, imagery, asset directories, and description JSON files under a CityUsd data directory following the spec search order and selection rules.

## Files created

| File | Purpose |
|------|---------|
| `tools/cityusd/scan_inputs.py` | `FoundInputs` + `scan_data_dir` |
| `tests/test_scan_inputs.py` | 8 unit tests |

## Implementation notes

- **OSM:** Search `data_dir/osm/` then `data_dir` root (non-recursive). Prefer first sorted `*.osm.pbf`, else first sorted `*.osm`.
- **DEM:** Largest `*.tif`/`*.tiff` in `data_dir/dem/` (recursive via `rglob`), then root (non-recursive `glob`).
- **Imagery:** Largest `*.tif`/`*.tiff`/`*.png` in `data_dir/imagery/` (recursive), then root; excludes path chosen as DEM.
- **Descriptions:** Sorted `data_dir/descriptions/*.json` (non-recursive).
- **Assets:** Returns `data_dir/assets` when that directory exists, else `None`.
- Search is limited to named subfolders and data root; no recursion into unrelated trees.

## TDD RED phase

Command:

```
PYTHONPATH=E:\UEWork\ROS2Test\CityUsd\tools pytest tests/test_scan_inputs.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 0 items / 1 error

=================================== ERRORS ====================================
_________________ ERROR collecting tests/test_scan_inputs.py __________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_scan_inputs.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_scan_inputs.py:3: in <module>
    from cityusd.scan_inputs import scan_data_dir
E   ModuleNotFoundError: No module named 'cityusd.scan_inputs'
=========================== short test summary info ===========================
ERROR tests/test_scan_inputs.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.06s ===============================
```

Expected: FAIL (import error) — confirmed.

## TDD GREEN phase

Command:

```
PYTHONPATH=E:\UEWork\ROS2Test\CityUsd\tools pytest tests/test_scan_inputs.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 8 items

tests/test_scan_inputs.py::test_prefers_pbf PASSED                       [ 12%]
tests/test_scan_inputs.py::test_missing_osm PASSED                       [ 25%]
tests/test_scan_inputs.py::test_osm_subdir_before_root PASSED            [ 37%]
tests/test_scan_inputs.py::test_dem_largest_in_dem_dir PASSED            [ 50%]
tests/test_scan_inputs.py::test_imagery_excludes_dem PASSED              [ 62%]
tests/test_scan_inputs.py::test_descriptions_json PASSED                 [ 75%]
tests/test_scan_inputs.py::test_assets_dir PASSED                        [ 87%]
tests/test_scan_inputs.py::test_assets_missing PASSED                    [100%]

============================== 8 passed in 0.03s ==============================
```

Full suite (`pytest tests/ -v`): 11 passed (3 CRS + 8 scan_inputs).

## Tests added (beyond brief minimum)

| Test | Validates |
|------|-----------|
| `test_osm_subdir_before_root` | `osm/` searched before root |
| `test_dem_largest_in_dem_dir` | Largest GeoTIFF in `dem/` |
| `test_imagery_excludes_dem` | Imagery skips DEM file |
| `test_descriptions_json` | Sorted JSON list |
| `test_assets_dir` / `test_assets_missing` | Assets directory detection |

## Concerns / deferred

- OSM "first" uses sorted filename order for determinism; spec does not define tie-breaking beyond PBF preference.
- DEM/imagery root search is non-recursive only; nested rasters outside named subfolders are not discovered.
- No integration test against real `CityUsd/data/` tree (deferred to later pipeline tasks).
