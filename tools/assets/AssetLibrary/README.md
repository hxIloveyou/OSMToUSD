# AssetLibrary (project-local)

Unified asset library for OSM base materials and overlay meshes.

Built by `Tools/scripts/rebuild_asset_library_from_web.py` into this folder
(`tools/assets/AssetLibrary` in CityUsd; mirrored under USDManager as needed).

## Layout

```text
AssetLibrary/
  catalog.json
  materials/          # albedo maps + materials_table.json
  meshes/
    buildings/ roads/ vegetation/ water/
    props/ equipment/
    obstacles/static|dynamic/
  schemas/
  LICENSES.md
  _downloads/         # cached zip sources (safe to delete)
  materials/buildings/inbox/   # 候选贴图：facades / roofs / signage / details（未接入 USD）
```

## Usage

1. Base layer: bind OSM features via `materials/materials_table.json`.
2. Overlay: resolve `asset_id` from `catalog.json`.
3. Mesh convention: +X forward, +Z up target; glTF files are Y-up on disk; use `bake_rotz_deg` when listed.
