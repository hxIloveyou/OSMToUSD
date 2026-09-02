# Scene Package Pipeline — Schema v0.3

CityUsd / USDManager 共用的 **Scene Package 构建契约**。  
实现入口：`tools/build_scene_pipeline.py`。

## 相对 v0.2 的变更

1. **导航产物**统一在 `nav2/connected/`（connected 二值 PGM + 完整 YAML 包）。
2. 根目录 **`nav/` 不再由 pipeline 写入**（遗留包可保留，用户自行清理）。
3. 新增 **`nav2_nature`** step：从 `terrain/dem_utm.tif` 生成 `nav2/nature/`（BMP + 坡度 PGM + `nature_bmp.yaml`）。
4. 实验版栅格（3m、mppi、roads_x* 等）**不自动生成**；手动脚本输出到 `nav2/variants/<name>/`。

## 目录布局（cityusd_v1 + nav2）

```
ScenePackages/<scene_id>/
  terrain/
  nav2/
    connected/
    nature/
    dem/
    variants/
  layers/
  ...
```

## Step 列表

| Step | 说明 |
|------|------|
| `nav_pgm` | OSM connected → `nav2/connected/` |
| `nav2_nature` | DEM 坡度 → `nav2/nature/` |

## meta.json nav 字段

```json
"nav": {
  "map_pgm": "./nav2/connected/map.pgm",
  "map_yaml": "./nav2/connected/map_local.yaml",
  "map_yaml_utm": "./nav2/connected/map.yaml",
  "valhalla_origin": "./nav2/connected/valhalla_origin.yaml",
  "cost_pgm": "./nav2/connected/cost.pgm"
}
```

## 发布工作流（dated scene id + 备份）

- `examples/taibei_ue.pipeline.yaml`：`scene.id` 为空，`runtime.scene_id_stamp: date` → `taibei_ue_YYYYMMDD`
- `runtime.backup_previous_packages: true`：跑前将 `output/ScenePackages/` 下其他 `taibei_ue_*` 目录 zip 到 `backups/`
- 固定 id 复现/增量：用 `examples/taibei_ue_20260831.pipeline.yaml`（不自动备份 sibling）

```bash
python tools/build_scene_pipeline.py --preset taibei_ue
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml --release
```
