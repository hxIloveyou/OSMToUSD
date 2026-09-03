# Scene Package Pipeline — Schema v0.3

CityUsd / USDManager 共用的 **Scene Package 构建契约**。  
实现入口：`tools/build_scene_pipeline.py`。

## 相对 v0.2 / 早期 v0.3 的变更

1. **场景根目录**改为 `SceneData/{scene_id}/`（不再默认写入 `output/ScenePackages/`）。
2. **USD 与 CostMap 分离**：
   - `output/USD/` — World、layers、textures、catalog…
   - `output/CostMap/2D/` — 原 `nav2/*`（connected / nature / variants / dem）
   - `output/CostMap/3D/` — 预留空目录（外部 3D cost 工具）
3. **共享资产**在 `tools/assets/`（跨场景），不进 SceneData。
4. 场景级对齐元数据：`SceneData/{id}/scene_alignment.json`（CostMap/2D 下有镜像）。

## 目录布局

```text
SceneData/<scene_id>/
  input/{osm,dem,imagery}/
  output/
    USD/
      World_*.usda
      layers/
      meta.json
      …
    CostMap/
      2D/
        connected/
        nature/
        dem/
        variants/          # 手动实验栅格
      3D/                  # placeholder
  scene_alignment.json
```

## Step 列表

| Step | 说明 |
|------|------|
| `nav_pgm` | OSM connected → `CostMap/2D/connected/` |
| `nav2_nature` | DEM 坡度 → `CostMap/2D/nature/` |
| `package_zip` | 打包整个 `output/`（USD + CostMap） |

## meta.json nav 字段（相对 USD 根）

```json
"nav": {
  "map_pgm": "../CostMap/2D/connected/map.pgm",
  "map_yaml": "../CostMap/2D/connected/map_local.yaml",
  "map_yaml_utm": "../CostMap/2D/connected/map.yaml",
  "valhalla_origin": "../CostMap/2D/connected/valhalla_origin.yaml",
  "cost_pgm": "../CostMap/2D/connected/cost.pgm"
}
```

## 发布工作流

- `examples/taibei_ue.pipeline.yaml`：固定 `scene.id: taibei_ue`，写入 `SceneData/taibei_ue/`
- `runtime.backup_previous_packages: true`：备份 `SceneData/` 下同前缀的其它场景目录
- 遗留包仍可读：`output/ScenePackages/`（勿删直至验证完成）

```bash
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml
```
