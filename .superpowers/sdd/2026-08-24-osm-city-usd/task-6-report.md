# Task 6 Report: Roads — width, overlap, GB 5768 markings, arrows, signs

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git; skipped per instructions)

## Summary

Implemented road width lookup, motor-highway filter, LineString buffering, hierarchy difference with extra junction polygons, GB 5768 `marking_kind` table, edge offsets, one-way junction arrows, and named-road sign placements in `tools/cityusd/roads.py` with TDD. Marking strips are `LineString.buffer(0.08)` at z = roads + 0.01 m. Arrows are single-direction 2.0×0.8 m triangles (no two-way opposing-arrow texture).

## Files created

| File | Purpose |
|------|---------|
| `tools/cityusd/roads.py` | Width, hierarchy cut, markings, arrows, signs |
| `tests/test_roads.py` | lanes override, primary double yellow, footway not motor |

## Implementation notes

- `way_width_m`: `width` float → `lanes * 3.5` → `ROAD_WIDTH_M` (unknown → 5.0).
- Hierarchy: lower rank `difference_safe` against higher; pairwise overlaps `unary_union` → extra `OsmWay` with `highway=junction`.
- `marking_kind` follows the brief table exactly (motorway/trunk/primary double yellow; secondary width gate 9 m; tertiary lane gate 8 m; residential center gate 6 m).
- Arrows: degree ≥ 3, 8 m setback, 2.0×0.8 m triangle pointing into the junction.
- Signs: motor + name/`name:zh`/`name:en`, spacing default 100 m, right offset `width/2 + 0.6` m.

## TDD RED phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_roads.py -v
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
____________________ ERROR collecting tests/test_roads.py _____________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_roads.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_roads.py:1: in <module>
    from cityusd.roads import way_width_m, marking_kind, is_motor_highway
E   ModuleNotFoundError: No module named 'cityusd.roads'
=========================== short test summary info ===========================
ERROR tests/test_roads.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.06s ===============================
```

Expected: FAIL (import error) — confirmed.

## TDD GREEN phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_roads.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 3 items

tests/test_roads.py::test_width_lanes_override PASSED                    [ 33%]
tests/test_roads.py::test_primary_double_yellow PASSED                   [ 66%]
tests/test_roads.py::test_footway_not_motor PASSED                       [100%]

============================== 3 passed in 0.14s ==============================
```

Expected: PASS — confirmed.

## Concerns

1. **Pytest coverage is the three brief tests only.** Hierarchy cut, junction union, arrows, signs, and marking strips were smoke-checked locally, not in `test_roads.py`.
2. **Junction vs higher-rank road:** overlap is emitted as an extra `highway=junction` poly; the higher-rank polygon is not subtracted, so the junction face still overlaps the higher road (lower rank is cut).
3. **Arrow size:** docstring says 2.5 m; Step 3 says triangle 2.0×0.8 m — implementation uses 2.0×0.8 m.
4. **Lane dashes at ±width/4** whenever `lane=white_dash`; two-lane primaries may look over-marked.
5. **`graph_degree` keys** are coordinate tuples (mm-rounded fallback), not OSM node ids.
