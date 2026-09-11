# Scene Package Pipeline — Schema v0.3

CityUsd / USDManager 共用的 **Scene Package 构建契约**。  
实现入口：`tools/build_scene_pipeline.py`。

## 目录布局

```text
SceneData/<scene_id>/
  input/
    osm/ dem/ imagery/
    config/
      pipeline.yaml          # 场景编排（可 extends: default/pipeline.yaml）
      terrain.json           # 整套 step 配置（从 default 复制后按场景改）
      osm_city_usd.json
      nav_pgm.json
      …
  output/
    <scene_id>-USD/
      configs/               # 运行产物 *.resolved.json（不是输入配置）
    <scene_id>-CostMap/
      2D/connected/
      3D/
  backups/

configs/default/             # 新场景模板；场景缺某文件时作 merge 底
  pipeline.yaml
  terrain.json
  osm_city_usd.json
  …
```

变体用不同 `scene_id`，不要在同一场景下堆多个 pipeline 变体。  
个性化改 `SceneData/<id>/input/config/`，不要改 default（除非改全局模板）。

## 配置解析

1. `extends: [default/pipeline.yaml]` → `configs/default/pipeline.yaml`
2. Step `config_ref: osm_city_usd.json`（或省略时尝试 `{step}.json`）：
   - 先读 `configs/default/<name>`
   - 再 deep-merge `SceneData/<id>/input/config/<name>`（若存在）
   - 再 merge step 内联 `config:`

## Step 要点

| Step | 说明 |
|------|------|
| `nav_pgm` | OSM → `{id}-CostMap/2D/connected/`；另写 `map_soft.pgm`（软边 2 m，仅可视化） |
| `nav_octomap` | OSM+DEM → `{id}-CostMap/3D/{prefix}.bt` + `_meta.json`（OctoMap；原点默认对齐场景 frame） |
| `package_zip` | 打包整个 `output/` |
| 开跑前 | `backup_output_before_run`：把已有 `output/` 打日期 zip（排除 `*.zip`） |

## 运行

```bash
python tools/build_scene_pipeline.py --scene taibei_ue
python tools/build_scene_pipeline.py --scene taibei_debug --only resolve_extent,osm_city_usd
python tools/build_scene_pipeline.py --config SceneData/taibei_ue/input/config/pipeline.yaml
```

`examples/*.pipeline.yaml` / `presets/*.yaml` 仅为兼容入口，转发到 `SceneData/.../input/config/`。
