# CityUsd v2 — OSM → UE Scene Package (SceneData layout)

> Worktree: `E:\UEWork\ROS2Test\CityUsd_v2` · branch `scenedata-v2`  
> Legacy layout remains at `E:\UEWork\ROS2Test\CityUsd` (`main`, `data/` + `output/ScenePackages/`).

Python tools that turn OSM (+ optional DEM/imagery) into a UE-oriented Scene Package
with city USD layers and Nav2 cost maps. Intended for later integration into **USDManager**.

## Directory layout

```text
CityUsd/
  SceneData/
    {scene_id}/
      input/{osm,dem,imagery}/
      output/
        {scene_id}-USD/              # World, layers, textures, …
        {scene_id}-CostMap/
          2D/connected/              # map.pgm, cost.pgm, map_soft.pgm, yaml
          3D/                        # placeholder
      backups/                       # dated zips of previous output/
      scene_alignment.json
  tools/
    assets/                          # shared AssetLibrary
    cityusd/
    build_scene_pipeline.py
```

| Path | Role |
|------|------|
| `…/output/{id}-USD` | Geometry USD package |
| `…/output/{id}-CostMap/2D` | Nav / cost rasters (`map_soft.pgm` = 2 m soft edge, viz only) |
| `…/output/{id}-CostMap/3D` | Placeholder for external 3D cost |
| `…/backups/` | Auto zip of previous `output/` before regenerate (`*.zip` excluded) |
| `tools/assets` | Shared assets |

## Quick start

```powershell
cd E:\UEWork\ROS2Test\CityUsd_v2
$env:PYTHONPATH="tools"
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml
```

## Recovery

- Git remote: `origin` → GitHub `hxIloveyou/OSMToUSD`
- Do not delete legacy `CityUsd/` until the new layout is validated
