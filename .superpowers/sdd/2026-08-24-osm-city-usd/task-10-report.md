# Task 10 Report: USD layers, PointInstancer, package metadata

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git; skipped per instructions)

## Summary

Implemented USD writers in `tools/cityusd/usd_write.py` and package helpers in `tools/cityusd/package.py`. Stages use `metersPerUnit=0.01` and Z-up; World defaultPrim is `World` with spec §5 `subLayers`; overlays are empty named Xforms; terrain/nav store relative paths in customData plus an optional invisible 1×1 plane; trees/lamps use PointInstancer + standalone prototype USDA files; `meta.json` carries required spec_version, units, lod, and instancer flags.

## Files created

| File | Purpose |
|------|---------|
| `tools/cityusd/usd_write.py` | Mesh, PointInstancer, prototype, environment/terrain/nav layers, materials/stripes |
| `tools/cityusd/package.py` | World, empty overlays, `write_meta` / `build_package_meta`, prototype files |
| `tests/test_usd_package.py` | Brief smoke `test_world_opens` plus overlay/terrain/instancer/meta tests |

## Implementation notes

- `configure_stage`: CreateNew, `UsdGeom.SetStageMetersPerUnit(0.01)`, `SetStageUpAxis(Z)`, defaultPrim `/World`.
- `WORLD_SUBLAYERS` matches spec §5 (environment → terrain → nav → base_osm → five overlays).
- Overlay prims: Equipment, Infrastructure, ObstaclesStatic, ObstaclesDynamic, Props under `/World/Overlay/`.
- Prototypes: `models/prototypes/tree.usda` and `lamp.usda` from furniture placeholder meshes; PointInstancer `prototypes` relationship + positions in centimeters + Z-yaw quaternions.
- Terrain/nav customData: `heightmap_png`, `ortho_png`, `map_pgm`, `map_yaml` (empty string if missing). Invisible RefPlane at Z=-1 cm.

## TDD RED phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_usd_package.py -v
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
_________________ ERROR collecting tests/test_usd_package.py __________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_usd_package.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_usd_package.py:5: in <module>
    from cityusd.package import write_world, write_empty_overlay
E   ModuleNotFoundError: No module named 'cityusd.package'
=========================== short test summary info ===========================
ERROR tests/test_usd_package.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.17s ===============================
```

Expected: FAIL (import error) — confirmed.

## TDD GREEN phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_usd_package.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 6 items

tests/test_usd_package.py::test_world_opens PASSED                       [ 16%]
tests/test_usd_package.py::test_world_up_axis_and_sublayers PASSED       [ 33%]
tests/test_usd_package.py::test_overlay_empty_xforms PASSED              [ 50%]
tests/test_usd_package.py::test_terrain_nav_custom_data PASSED           [ 66%]
tests/test_usd_package.py::test_point_instancer_and_prototype PASSED     [ 83%]
tests/test_usd_package.py::test_prototype_files_and_meta PASSED          [100%]

============================== 6 passed in 0.49s ==============================
```

Expected: PASS — confirmed.

Full suite: `pytest tests -v` → **32 passed**.

## Concerns

1. **City layer not assembled here** — `write_building_cell`, material binding, stripe PNGs, and PointInstancer→`tree.usda`/`lamp.usda` references are helpers for Task 11; no `base_osm` composition test.
2. **`RasterMeta` extra customData** (`crs_epsg`, `range_source`) is untested; missing raster paths become empty strings rather than omitted keys.
3. **Invisible RefPlane is written on both terrain and nav**; spec called it optional. Nav plane is extra.
4. **No git commit** per workspace / task instructions.
