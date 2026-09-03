# CityUsd v2 — OSM → UE Scene Package (SceneData layout)

> Worktree: `E:\UEWork\ROS2Test\CityUsd_v2` · branch `scenedata-v2`  
> Legacy layout remains at `E:\UEWork\ROS2Test\CityUsd` (`main`, `data/` + `output/ScenePackages/`).

Python tools that turn OSM (+ optional DEM/imagery) into a UE-oriented Scene Package
with city USD layers and Nav2 cost maps. Intended for later integration into **USDManager**.

## Directory layout

```text
CityUsd/
  SceneData/
    {scene_id}/                 # scene library id (e.g. taibei_ue)
      input/                    # scene-private inputs
        osm/
        dem/
        imagery/
      output/
        USD/                    # World, layers, textures, models, catalog, …
        CostMap/
          2D/                   # nav connected / variants / nature (PGM+yaml)
          3D/                   # reserved empty (external 3D cost tools)
      scene_alignment.json      # shared meta: resolution, center, extent, paths
  tools/
    assets/                     # shared AssetLibrary (facades, meshes, …)
    cityusd/                    # library code
    build_scene_pipeline.py     # CLI entry
    …
  configs/ presets/ examples/ tests/ docs/
```

| Path | Role |
|------|------|
| `SceneData/{id}/input` | Per-scene OSM / DEM / ortho |
| `SceneData/{id}/output/USD` | Geometry USD package (no nav2 tree) |
| `SceneData/{id}/output/CostMap/2D` | All 2D nav / cost rasters |
| `SceneData/{id}/output/CostMap/3D` | Placeholder for others' 3D cost output |
| `tools/assets` | Shared assets across scenes |
| `tools/` | Pipeline scripts & `cityusd` package |
| `output/ScenePackages/` | **Legacy** packages (kept for rollback; prefer SceneData) |
| `data/` | **Legacy** inputs (kept for rollback; prefer SceneData/input) |

## Quick start

```powershell
cd E:\UEWork\ROS2Test\CityUsd
$env:PYTHONPATH="tools"
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml
```

Results land under `SceneData/taibei_ue/output/…`. Alignment metadata:

- `SceneData/{id}/scene_alignment.json`
- `SceneData/{id}/output/CostMap/2D/scene_alignment.json`

## Recovery

- Git remote: `origin` → GitHub `hxIloveyou/OSMToUSD`
- Do not delete legacy `data/` / `output/ScenePackages/` until the new layout is validated
