# Scene Package Pipeline — Schema v0.3

CityUsd / USDManager 共用的 **Scene Package 构建契约**。  
实现入口：`tools/build_scene_pipeline.py`。

## 目录布局

```text
SceneData/<scene_id>/
  input/{osm,dem,imagery}/
  output/
    <scene_id>-USD/
    <scene_id>-CostMap/
      2D/connected/     # map.pgm + cost.pgm + map_soft.pgm
      3D/
  backups/              # <scene_id>_output_YYYYMMDD_HHMMSS.zip
  scene_alignment.json
```

## Step 要点

| Step | 说明 |
|------|------|
| `nav_pgm` | OSM → `{id}-CostMap/2D/connected/`；另写 `map_soft.pgm`（软边 2 m，仅可视化） |
| `package_zip` | 打包整个 `output/` |
| 开跑前 | `backup_output_before_run`：把已有 `output/` 打日期 zip（排除 `*.zip`） |

## meta.json nav（相对 USD 根）

```json
"nav": {
  "map_pgm": "../{scene_id}-CostMap/2D/connected/map.pgm",
  "map_soft_pgm": "../{scene_id}-CostMap/2D/connected/map_soft.pgm",
  "cost_pgm": "../{scene_id}-CostMap/2D/connected/cost.pgm"
}
```

```bash
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml
```
