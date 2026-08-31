# Task 5 Report: Geometry helpers

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git; skipped per instructions)

## Summary

Implemented `triangulate_polygon`, `to_mesh_cm`, and `difference_safe` in `tools/cityusd/geom.py` with TDD. Triangulation uses `mapbox_earcut.triangulate_float64` with per-ring vertex counts; polygons with area &lt; 0.05 m² or invalid/empty geometry return empty verts/faces. `to_mesh_cm` converts XY meters and Z layer height to centimeters via `CM_PER_M` and flattens face indices.

## Files created

| File | Purpose |
|------|---------|
| `tools/cityusd/geom.py` | earcut triangulation, cm mesh conversion, safe difference |
| `tests/test_geom.py` | unit-square triangulation + z conversion test |

## Implementation notes

- Ring extraction: exterior + interiors; drop closing duplicate coordinate per ring.
- `MIN_AREA_M2 = 0.05` gate before earcut.
- `difference_safe`: returns original geom on empty cutter, empty result, or exception.
- `LAYER_Z_M` consumed by callers (e.g. roads at 0.08 m); test uses explicit `z_m=0.08`.

## TDD RED phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_geom.py -v
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
_____________________ ERROR collecting tests/test_geom.py _____________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_geom.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_geom.py:3: in <module>
    from cityusd.geom import triangulate_polygon, to_mesh_cm
E   ModuleNotFoundError: No module named 'cityusd.geom'
=========================== short test summary info ===========================
ERROR tests/test_geom.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.18s ===============================
```

Expected: FAIL (import error) — confirmed.

## TDD GREEN phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_geom.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 1 item

tests/test_geom.py::test_unit_square_two_tris PASSED                     [100%]

============================== 1 passed in 0.11s ==============================
```

Expected: PASS — confirmed.

## Concerns

1. **`difference_safe` untested:** Brief only specified triangulation/mesh test; boolean fallback behavior not covered by pytest.
2. **MultiPolygon / GeometryCollection:** `triangulate_polygon` assumes `.exterior`/`.interiors`; callers must pass single `Polygon` instances.
3. **Tiny sliver polygons:** Area gate at 0.05 m² silently drops small features; downstream may need logging if gaps appear.
