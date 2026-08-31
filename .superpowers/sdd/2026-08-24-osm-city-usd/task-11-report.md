# Task 11 Report: CLI orchestrator and tiny-OSM integration test

**Date:** 2026-08-24  
**Status:** Complete  
**Commits:** none (no git; skipped per instructions)

## Summary

Implemented `tools/build_city_usd.py` as the Scene Package orchestrator and `tests/test_build_cli.py` (tiny package + missing-OSM). PYTHONPATH is `tools/` + workspace root so tests can `from build_city_usd import main` while `cityusd.*` still imports. `main(argv) -> int` returns 1 and writes nothing when OSM is missing; `__main__` does `sys.exit(main())`. Tiny World opens with composed City meshes (roads, markings, extruded buildings LOD0/1/2, water) plus a tree PointInstancer. Production city layer is `layers/base_osm.usdc` (pxr CreateNew crate works); `.usda` fallback remains if crate create fails. No DEM drape: geometry at Z=0 plus `LAYER_Z_M` offsets.

## Files created / updated

| File | Purpose |
|------|---------|
| `tools/build_city_usd.py` | CLI: scan → parse → rasters → roads/buildings/water/veg/furniture → PGM → USD package |
| `tests/test_build_cli.py` | Brief tests `test_tiny_package` and `test_missing_osm_exits` |
| `tools/cityusd/usd_write.py` | Sanitize negative LOD cell ids (`c0_-1` is illegal USD; now `c0_n1`) |

## Implementation notes

- Origin/extent: DEM geographic center + DEM rectangle in local m (`range_source=dem`); else OSM bbox center (`osm_bbox`). Re-parse OSM with DEM origin.
- Heightmap/ortho written only when DEM/imagery exist; otherwise warn and skip files. `terrain.usda` / overlays still written.
- Roads: width buffer → hierarchy subtract → markings/arrows/signs. Buildings minus roads; water/veg minus roads+buildings.
- PGM occupied = buildings + water; free = motor highway polygons. Default `--pgm-resolution 1.0`.
- City meshes via `write_mesh` / `write_building_cell` / `write_point_instancer`; prototypes also copied to `models/prototypes/`.
- Description JSON: `--description` and `data/descriptions/*.json` recorded only in `sources_manifest.json`; overlay prims stay empty.
- `scene_id` default `{osm.stem}_{YYYYMMDD}`. Per-feature triangulation/extrude failures increment `skipped` and print a summary.
- `main` inserts `tools/` and its parent on `sys.path`.

## TDD RED phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools;E:\UEWork\ROS2Test\CityUsd"; python -m pytest tests/test_build_cli.py -v
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
__________________ ERROR collecting tests/test_build_cli.py ___________________
ImportError while importing test module 'E:\UEWork\ROS2Test\CityUsd\tests\test_build_cli.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
D:\SoftWare\Anaconda\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests\test_build_cli.py:4: in <module>
    from build_city_usd import main
E   ModuleNotFoundError: No module named 'build_city_usd'
=========================== short test summary info ===========================
ERROR tests/test_build_cli.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.17s ===============================
```

Expected: FAIL import `build_city_usd` — confirmed.

## TDD GREEN phase

Command:

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools;E:\UEWork\ROS2Test\CityUsd"; python -m pytest tests/test_build_cli.py -v
```

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 2 items

tests/test_build_cli.py::test_tiny_package PASSED                        [ 50%]
tests/test_build_cli.py::test_missing_osm_exits PASSED                   [100%]

============================== 2 passed in 0.49s ==============================
```

Expected: PASS — confirmed.

Full suite: `python -m pytest tests -v` → **34 passed**.

Tiny probe (not committed): World subLayers include `./layers/base_osm.usdc`; composed meshes include road, marking, `Buildings/c0_n1/LOD0..2`, water; `I_Trees` has 1 instance; overlay Equipment empty; no heightmap. Summary: `roads=1 buildings=1 water=1 markings=1 signs=1 trees=1 skipped=0`.

## Concerns

1. **Negative LOD cell names** required a Task 10 helper change (`write_building_cell`); OSM origin at bbox center routinely yields negative `iy`.
2. **LOD1/LOD2 share the LOD0 extruded mesh** in a cell (no simplified far mesh); UE can still switch by name/`switch_distance_m`.
3. **`skipped` also counts empty triangulations** (area &lt; `MIN_AREA_M2`), not only exceptions.
4. **`main` returns 1** on missing OSM (pytest-friendly); process exit is only via `__main__`.
5. **No git commit** per workspace / task instructions.
