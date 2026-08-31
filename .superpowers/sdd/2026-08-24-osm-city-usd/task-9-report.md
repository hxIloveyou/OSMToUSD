# Task 9 Report: PGM occupancy

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git; skipped per instructions)

## Summary

Implemented Nav2 occupancy export in `tools/cityusd/pgm.py`: ceil-sized grid, fill 205 → burn free 254 → occupied 0, binary P5 PGM (row 0 = north), `map.yaml` with SW origin, and `map_meta.json` matching heightmap fields plus `range_source`.

## Files created

| File | Purpose |
|------|---------|
| `tools/cityusd/pgm.py` | `rasterize_pgm` + PGM/YAML/JSON writers |
| `tests/test_pgm.py` | Brief smoke: P5 header + YAML origin |

## Implementation notes

- Grid: `nx/ny = ceil(extent.{width,height} / resolution_m)`.
- Rasterize via `rasterio.features.rasterize` + `from_bounds` (north-up).
- YAML `origin: [float(west), float(south), 0.0]` so int ctor args still emit `.0`.
- `meters_per_pixel = (resolution_m, resolution_m)`; `zmin_m`/`zmax_m` = null.

## TDD RED phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_pgm.py -v
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
_____________________ ERROR collecting tests/test_pgm.py ______________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_pgm.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_pgm.py:4: in <module>
    from cityusd.pgm import rasterize_pgm
E   ModuleNotFoundError: No module named 'cityusd.pgm'
=========================== short test summary info ===========================
ERROR tests/test_pgm.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.19s ===============================
```

Expected: FAIL (import error) — confirmed.

## TDD GREEN phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_pgm.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 1 item

tests/test_pgm.py::test_building_is_occupied PASSED                      [100%]

============================== 1 passed in 0.25s ==============================
```

Expected: PASS — confirmed.

## Concerns

1. **Brief test does not assert pixel values** (building=0, road=254, unknown=205) or occupied-over-free precedence.
2. **`from_bounds` stretches** to exact extent; with non-divisible extents, cell size ≠ `resolution_m` slightly vs affine `resolution_m` grid that may overhang.
3. **Heightmap meta still omits `range_source` in JSON**; PGM adds it per brief — field sets diverge slightly.
