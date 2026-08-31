# Task 1 Report: Scaffold, types, CRS

**Date:** 2026-08-24  
**Status:** DONE  
**Work directory:** `E:\UEWork\ROS2Test\CityUsd`

## Summary

Implemented the `cityusd` package scaffold with shared types (`Origin`, `ExtentM`, `RasterMeta`, `LAYER_Z_M`, `CM_PER_M`) and CRS helpers (`utm_epsg`, `make_origin`, `lonlat_to_local`, `local_to_lonlat`, `extent_from_lonlat_bbox`). Followed TDD: failing test first, confirmed RED, implemented, confirmed GREEN (3/3 passed).

## Files Created

| File | Purpose |
|------|---------|
| `tools/requirements.txt` | Runtime and test dependencies per plan |
| `tools/cityusd/__init__.py` | Package marker |
| `tools/cityusd/types.py` | Shared dataclasses and constants |
| `tools/cityusd/crs.py` | UTM EPSG, origin, lon/lat ↔ local meters |
| `tests/test_crs.py` | CRS unit tests (Taipei EPSG, origin zero, roundtrip) |

## Implementation Notes

- **`utm_epsg(lon, lat)`** — Two-argument form per Step 3 correction: zone from longitude, northern hemisphere base 32600. Taipei `(121.53296235, 25.04756678)` → EPSG 32651.
- **`make_origin`** — Stores `lon`, `lat`, `height_m`, and computed `epsg` on `Origin`.
- **`lonlat_to_local` / `local_to_lonlat`** — `pyproj.Transformer.from_crs` with `always_xy=True`; local coords are UTM east/north relative to origin.
- **`extent_from_lonlat_bbox`** — Converts four bbox corners to local meters and returns `ExtentM` min/max envelope (not covered by tests in this task; exported for later tasks).

## TDD Evidence

### RED — Step 2 (before implementation)

**Command:**

```powershell
cd E:\UEWork\ROS2Test\CityUsd
pip install pytest pyproj -q
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"
pytest tests/test_crs.py -v
```

**Output:**

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 0 items / 1 error

=================================== ERRORS ====================================
_____________________ ERROR collecting tests/test_crs.py ______________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_crs.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_crs.py:2: in <module>
    from cityusd.crs import lonlat_to_local, local_to_lonlat, make_origin, utm_epsg
E   ModuleNotFoundError: No module named 'cityusd'
=========================== short test summary info ===========================
ERROR tests/test_crs.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.11s ===============================
```

**Result:** FAIL as expected (`ModuleNotFoundError: cityusd`).

### GREEN — Step 4 (after implementation)

**Command:**

```powershell
cd E:\UEWork\ROS2Test\CityUsd
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"
pytest tests/test_crs.py -v
```

**Output:**

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 3 items

tests/test_crs.py::test_taipei_epsg PASSED                               [ 33%]
tests/test_crs.py::test_origin_is_zero PASSED                            [ 66%]
tests/test_crs.py::test_roundtrip PASSED                                 [100%]

============================== 3 passed in 0.11s ==============================
```

**Result:** PASS — all 3 tests green.

## Self-Review

| Check | Result |
|-------|--------|
| `utm_epsg(121.53296235, 25.04756678) == 32651` | Pass |
| Origin at its own lon/lat maps to ~(0, 0) local | Pass (`< 1e-6`) |
| lon/lat roundtrip through local meters | Pass (`< 1e-7`) |
| Shared types match plan file map | Pass |
| `requirements.txt` matches brief | Pass |
| Git commit skipped (no repo) | N/A |

## Concerns

None. `extent_from_lonlat_bbox` is implemented but untested in Task 1; later tasks may add coverage.

## Commits

None (workspace has no git repository per instructions).
