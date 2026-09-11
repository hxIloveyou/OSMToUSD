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
      input/
        osm/ dem/ imagery/
        config/                      # full scene configs (edit here)
          pipeline.yaml
          osm_city_usd.json
          terrain.json …
      output/
        {scene_id}-USD/
        {scene_id}-CostMap/2D|3D/
      backups/
  configs/default/                   # template for new scenes (+ merge base)
    pipeline.yaml
    terrain.json
    osm_city_usd.json
    …
  tools/assets/                      # shared AssetLibrary
```

Variants = **separate `scene_id`** (e.g. `taibei_ue`, `taibei_debug`).

Step JSON merge order: `configs/default/{name}` → `SceneData/{id}/input/config/{name}` → step inline `config:`.  
Per-scene personalization: edit files under `SceneData/{id}/input/config/`.

| Path | Role |
|------|------|
| `…/input/config/` | Full scene pipeline + step configs (primary) |
| `configs/default/` | New-scene template / merge base if a file is missing |
| `…/output/{id}-USD` | Geometry USD package |
| `…/output/{id}-CostMap/2D` | Nav / cost rasters (PGM) |
| `…/output/{id}-CostMap/3D` | OctoMap (`.bt` + meta; pipeline `nav_octomap`) |
| `…/backups/` | Dated zip of previous `output/` before regenerate |

## Quick start

```powershell
cd E:\UEWork\ROS2Test\CityUsd_v2
$env:PYTHONPATH="tools"
python tools/build_scene_pipeline.py --scene taibei_ue
```

各脚本用途见 **[tools/README.md](tools/README.md)**。

## Recovery

- Git remote: `origin` → GitHub `hxIloveyou/OSMToUSD`
- Do not delete legacy `CityUsd/` until the new layout is validated
