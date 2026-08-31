# Task 8 Report: Water, vegetation, furniture instancers

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git; skipped per instructions)

## Summary

Implemented water/vegetation polygon extraction with road+building difference, tree/lamp instance poses, and centimeter placeholder meshes in `tools/cityusd/water_veg.py` and `tools/cityusd/furniture.py` with TDD. Lamps only on `primary`/`trunk`/`motorway`, both sides, spacing default 30 m, offset `width/2+0.4`. Difference exceptions skip the feature and increment module-level `skip_count`.

## Files created

| File | Purpose |
|------|---------|
| `tools/cityusd/water_veg.py` | Water/veg polygons, `WATERWAY_WIDTH_M`, `skip_count` |
| `tools/cityusd/furniture.py` | Tree/lamp instances + placeholder meshes (cm) |
| `tests/test_furniture.py` | Lamp filter + tree mesh faces |
| `tests/test_water_veg.py` | `tiny.osm` water → one polygon |

## Implementation notes

- Water areas: `natural=water`, `water=*`, `landuse=reservoir`; lines: `waterway` river/stream/canal buffered by half-width.
- Vegetation: `landuse` grass/forest/meadow, `leisure=park`, `natural=wood`.
- Cutters `None`/empty → no difference; exception → `skip_count += 1` and omit; empty result → omit.
- Tree nodes: `natural=tree` → `(x, y, 0.0)`.
- Placeholders: tree cylinder+cone; lamp cylinder+0.3 m cube; verts in cm, origin at ground center.

## TDD RED phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_furniture.py -v
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
__________________ ERROR collecting tests/test_furniture.py ___________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_furniture.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_furniture.py:1: in <module>
    from cityusd.furniture import lamp_instances, placeholder_tree_mesh
E   ModuleNotFoundError: No module named 'cityusd.furniture'
=========================== short test summary info ===========================
ERROR tests/test_furniture.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.06s ===============================
```

Expected: FAIL (import error) — confirmed.

## TDD GREEN phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_furniture.py tests/test_water_veg.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 3 items

tests/test_furniture.py::test_lamp_only_primary PASSED                   [ 33%]
tests/test_furniture.py::test_tree_placeholder_has_faces PASSED          [ 66%]
tests/test_water_veg.py::test_tiny_water_one_polygon PASSED              [100%]

============================== 3 passed in 0.19s ==============================
```

Expected: PASS — confirmed.

## Concerns

1. **Pytest coverage is brief-minimal.** `vegetation_polygons`, `tree_instances`, `placeholder_lamp_mesh`, waterway buffering, and `skip_count` paths are untested.
2. **`difference_safe` unused** for water/veg: brief requires skip + `skip_count` on failure rather than return-original.
3. **Lamp sampling** mirrors road signs (`d < length`); a 60 m primary at spacing 30 yields one station × two sides = 2 instances (meets `>= 2`).
