# Task 4 Report: DEM heightmap and ortho

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git; skipped per instructions)

## Summary

Implemented `write_heightmap` and `write_ortho` in `tools/cityusd/rasters.py` with TDD. DEM is reprojected to the origin UTM CRS, cropped to the local extent mapped into absolute UTM, resized with longest side 2049 (aspect kept, odd dims preferred), and written as 16-bit PNG (`I;16`) plus meta JSON. Ortho uses the same rectangle, longest side `max(4096, min(max_dim, 8192))`, 8-bit RGB PNG, zmin/zmax null in JSON.

## Files created

| File | Purpose |
|------|---------|
| `tools/cityusd/rasters.py` | `write_heightmap`, `write_ortho` |
| `tests/test_rasters.py` | heightmap export test |

## Implementation notes

- UTM crop: `utm_origin + (west/south/east/north)` local meters; north-up via `from_bounds`.
- Heightmap: bilinear `rasterio.warp.reproject`; pixel 0→zmin, 65535→zmax; `range_source="dem"`.
- Ortho: up to 3 bands (mono duplicated to RGB); values >255 scaled to 8-bit.
- JSON top-level keys: `size_px`, `zmin_m`, `zmax_m`, `origin_wgs84`, `utm_origin`, `extent_m`, `meters_per_pixel`, `crs_epsg`.
- `extent_m`: `east`/`north` = widths; `west`/`south` = local mins (local max = west+east, south+north).
- `meters_per_pixel = (extent.width/(size_px[0]-1), extent.height/(size_px[1]-1))`.

## TDD RED phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_rasters.py::test_heightmap_written -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... ERROR: not found: E:\UEWork\ROS2Test\CityUsd\tests\test_rasters.py::test_heightmap_written
(no name 'E:\\UEWork\\ROS2Test\\CityUsd\\tests\\test_rasters.py::test_heightmap_written' in any of [<Module tests/test_rasters.py>])

collected 0 items / 1 error

=================================== ERRORS ====================================
___________________ ERROR collecting tests/test_rasters.py ____________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_rasters.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_rasters.py:8: in <module>
    from cityusd.rasters import write_heightmap
E   ModuleNotFoundError: No module named 'cityusd.rasters'
=========================== short test summary info ===========================
ERROR tests/test_rasters.py
============================== 1 error in 0.24s ===============================
```

Expected: FAIL (import error) — confirmed.

## TDD GREEN phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_rasters.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 1 item

tests/test_rasters.py::test_heightmap_written PASSED                     [100%]

============================== 1 passed in 0.48s ==============================
```

Expected: PASS — confirmed.

## Concerns

1. **`extent_m` east/north naming:** Brief asks for east/north *widths* plus west/south/east/north *local*; storing both as top-level `east`/`north` collides. Implementation uses east/north as widths and west/south as local mins (local max = west+east, south+north). Confirm if consumers need explicit local max keys.
2. **Ortho untested in pytest:** `write_ortho` smoke-checked manually; no unit test in `test_rasters.py` (brief only specified heightmap test).
3. **Odd secondary dimension:** Shorter side is forced odd when possible; if rounding hits an edge case, aspect may shift by 1 px.
