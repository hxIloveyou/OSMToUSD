# Final fix wave (Important items)

Date: 2026-08-24  
Scope: CityUsd pipeline Important-item fixes after whole-branch review. No git. PYTHONPATH=`E:\UEWork\ROS2Test\CityUsd\tools`.

## Status

Done. All 11 listed items applied. pytest: **34 passed**.

## What was fixed

1. **Transformer cache** — `cityusd/crs.py` caches `pyproj.Transformer` per CRS pair (`lru_cache`). `lonlat_to_local` / `local_to_lonlat` cache origin UTM. `rasters.py` and `pgm.py` use `lonlat_to_utm` instead of constructing a Transformer per call.
2. **extent_m JSON** — `ExtentM.to_json()` stores `west,south,east,north` as min/max and `width,height` as derived. Used by rasters, PGM sidecars, and package `crs.extent_m`. Widths are never stored in keys named `east`/`north`.
3. **difference_safe** — empty successful difference is returned; original geom only on exception.
4. **is_motor_highway** — also excludes `cycleway`, `bridleway`, `corridor`, `construction`, `proposed`, `raceway`, `busway`.
5. **way_width_m** — parses `width` with optional `m` / `meter(s)` suffix (same pattern as building height).
6. **Heightmap** — vertex grid: `meters_per_pixel = extent/(size-1)` and reproject via `from_origin(left, top, mpp_x, mpp_y)` (north-up), matching JSON.
7. **PGM** — `nx/ny = ceil(extent/resolution)`; pad with `from_origin` so pixels stay square; YAML `resolution` equals actual m/px. If x≠y ever occurred, YAML would include `meters_per_pixel_xy`.
8. **Building material** — `write_building_cell` binds `/World/Looks/Building` by default.
9. **PointInstancer prototypes** — city layer references `../models/prototypes/tree.usda` and `lamp.usda`; placeholders remain in those files (`write_prototype_files`).
10. **LOD** — option (a): group at 200 m (LOD0), 800 m (LOD1 merged extrusions, `switch_distance_m=1500`), 3200 m (LOD2 = `unary_union` then extrude once, `switch_distance_m=6000`). Coarser cells use `c800_*` / `c3200_*` paths to avoid index collision. `has_building_lod` stays true.
11. **Invalid polygons** — `repair_polygon` (`make_valid` then `buffer(0)`) before skip in buildings, water, and vegetation.

Not in this wave (per brief): OSM relations/multipolygons; dashed-line / stop-line meshes; sign name textures.

## Leftover

- 200 m cell prims (`c{ix}_{iy}`) emit **LOD0 only**; LOD1/LOD2 live on separate `c800_*` / `c3200_*` parents (avoids overlapping copies). UE sibling-LOD under a single 200 m parent is not used.
- Ortho still uses `from_bounds` (pixel-as-area) while JSON `meters_per_pixel` is still `extent/(size-1)`. Heightmap-only item.
- PGM grid may extend slightly past `extent_m` when width/height are not multiples of resolution (pad/ceil). Origin stays `(west, south)`.

## Tests

Command:

```
PYTHONPATH=E:\UEWork\ROS2Test\CityUsd\tools
python -m pytest tests -v
```

Working directory: `E:\UEWork\ROS2Test\CityUsd`

Output:

```
============================= test session starts =============================
platform win32 -- Python 3.12.3, pytest-7.4.4, pluggy-1.5.0 -- D:\SoftWare\Anaconda\python.exe
cachedir: .pytest_cache
rootdir: E:\UEWork\ROS2Test\CityUsd
plugins: anyio-4.2.0, hydra-core-1.3.2
collecting ... collected 34 items

tests/test_build_cli.py::test_tiny_package PASSED                        [  2%]
tests/test_build_cli.py::test_missing_osm_exits PASSED                   [  5%]
tests/test_buildings.py::test_levels PASSED                              [  8%]
tests/test_buildings.py::test_default_10 PASSED                          [ 11%]
tests/test_buildings.py::test_cell PASSED                                [ 14%]
tests/test_crs.py::test_taipei_epsg PASSED                               [ 17%]
tests/test_crs.py::test_origin_is_zero PASSED                            [ 20%]
tests/test_crs.py::test_roundtrip PASSED                                 [ 23%]
tests/test_furniture.py::test_lamp_only_primary PASSED                   [ 26%]
tests/test_furniture.py::test_tree_placeholder_has_faces PASSED          [ 29%]
tests/test_geom.py::test_unit_square_two_tris PASSED                     [ 32%]
tests/test_osm_parse.py::test_parse_tiny_counts PASSED                   [ 35%]
tests/test_osm_parse.py::test_parse_tiny_pbf_counts PASSED               [ 38%]
tests/test_osm_parse.py::test_parse_empty_osm_raises PASSED              [ 41%]
tests/test_pgm.py::test_building_is_occupied PASSED                      [ 44%]
tests/test_rasters.py::test_heightmap_written PASSED                     [ 47%]
tests/test_roads.py::test_width_lanes_override PASSED                    [ 50%]
tests/test_roads.py::test_primary_double_yellow PASSED                   [ 52%]
tests/test_roads.py::test_footway_not_motor PASSED                       [ 55%]
tests/test_scan_inputs.py::test_prefers_pbf PASSED                       [ 58%]
tests/test_scan_inputs.py::test_missing_osm PASSED                       [ 61%]
tests/test_scan_inputs.py::test_osm_subdir_before_root PASSED            [ 64%]
tests/test_scan_inputs.py::test_dem_largest_in_dem_dir PASSED            [ 67%]
tests/test_scan_inputs.py::test_imagery_excludes_dem PASSED              [ 70%]
tests/test_scan_inputs.py::test_descriptions_json PASSED                 [ 73%]
tests/test_scan_inputs.py::test_assets_dir PASSED                        [ 76%]
tests/test_scan_inputs.py::test_assets_missing PASSED                    [ 79%]
tests/test_usd_package.py::test_world_opens PASSED                       [ 82%]
tests/test_usd_package.py::test_world_up_axis_and_sublayers PASSED       [ 85%]
tests/test_usd_package.py::test_overlay_empty_xforms PASSED              [ 88%]
tests/test_usd_package.py::test_terrain_nav_custom_data PASSED           [ 91%]
tests/test_usd_package.py::test_point_instancer_and_prototype PASSED     [ 94%]
tests/test_usd_package.py::test_prototype_files_and_meta PASSED          [ 97%]
tests/test_water_veg.py::test_tiny_water_one_polygon PASSED              [100%]

============================= 34 passed in 0.84s ==============================
```
