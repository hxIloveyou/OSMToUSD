# tools/ — 脚本说明

运行前在仓库根目录设置：

```powershell
$env:PYTHONPATH="tools"
```

主流程请优先用 **Scene Package 流水线**；本目录下其它脚本多为独立工具或调试/变体生成，一般**不会**改场景的 `pipeline.yaml`。

---

## 注释规范

`tools/*.py` 采用「英文对外 + 中文补充」：

1. **模块 docstring（英文）**：给 `argparse` / `--help` 用，保持英文。
2. **紧随其后的 `# 中文说明`**：补充用途/用法（可选）。
3. **函数 docstring**：英文一句话（若有）+ 中文「功能：…」补充。
4. **行内 `#` 注释**：中文说明非显而易见的业务意图；不改对外英文标识/路径名。

库代码 `cityusd/`：每个模块文件顶部有 `# 中文说明：…`；主要入口函数 docstring 含「功能：…」中文补充。英文技术 docstring / 标识符保持不变。

---

## 一、主入口（推荐）

| 脚本 | 用途 |
|------|------|
| **`build_scene_pipeline.py`** | **官方入口**。按场景配置跑完整流水线（extent → terrain → OSM USD → labels → nav PGM → OctoMap 3D → nature → overlay → World → zip）。 |

```powershell
python tools/build_scene_pipeline.py --scene taibei_ue
python tools/build_scene_pipeline.py --scene taibei_debug --only resolve_extent,osm_city_usd
python tools/build_scene_pipeline.py --config SceneData/taibei_ue/input/config/pipeline.yaml
python tools/build_scene_pipeline.py --scene taibei_ue --resume
```

常用参数：

- `--scene <id>`：读 `SceneData/<id>/input/config/pipeline.yaml`
- `--config <path>`：显式指定 pipeline 文件
- `--only a,b,c`：只跑列出的步骤
- `--resume`：跳过 manifest 中 input_hash 未变的步骤
- `--preset`：已弃用，等同 `--scene`

配置说明见仓库根 `README.md` 与 `docs/pipeline-schema-v0.3.md`。

---

## 二、城市 USD / 资产相关

| 脚本 | 用途 |
|------|------|
| **`build_city_usd.py`** | 底层：扫描数据并生成城市几何 USD（道路/建筑/水体等）。流水线里的 `osm_city_usd` 步骤会调用它；也可单独调试。 |
| **`download_facade_inbox.py`** | 下载 CC0 立面/屋顶贴图候选到 AssetLibrary inbox，**不重建** USD。 |
| **`build_roads_scaled_usd_package.py`** | 生成「道路加宽 ×N、压掉车行道上建筑」的旁路 Scene Package，用于导航/代价实验，不替代主包。 |

---

## 三、导航 / CostMap（PGM / OctoMap）相关

流水线内：`nav_pgm` → `CostMap/2D`；`nav_octomap` → `CostMap/3D`（`.bt`）。

这些脚本多在**已有**包上二次处理，写出 `variants/` 或旁路目录，默认不覆盖流水线产物。

| 脚本 | 用途 |
|------|------|
| **`build_nav_pgm_at_resolution.py`** | 按指定分辨率另建占据图（默认读 `configs/default/nav_pgm_3m.json`），写入旁路目录，不覆盖默认 `connected/`。 |
| **`build_nav_connected_pgm.py`** | 单独生成连通型 nav PGM（与流水线 `nav_pgm` 思路相近；旧包路径兼容）。 |
| **`run_nav2_nature.py`** | 在已有 Scene Package 上单独跑 `nav2_nature`（DEM → 坡度/悬崖 nature 层）。 |
| **`remap_pgm_roads_only.py`** | 后处理：占据图里只保留道路为可通行，写出 `variants/roads_only` 一类目录。 |
| **`build_road_cost_expand.py`** | 在 roads-only 图上按宽度倍率膨胀走廊，生成加宽道路代价图。 |
| **`build_mppi_cost_pgm.py`** | 从 roads-only 占据图生成 MPPI/局部规划友好的软代价 `cost.pgm`。 |
| **`downsample_pgm.py`** | 对单张占据 PGM 做整数倍降采样（保连通：块内任一自由则自由）。 |
| **`downsample_nav2_bundle.py`** | 对整套 nav2/connected 包（pgm+yaml+meta）降采样到更粗分辨率（默认约 3 m/px）。 |

---

## 四、场景数据辅助

| 位置 | 用途 |
|------|------|
| **`SceneData/taibei_ue/input/osm/crop_center_500m.py`** | 从 `taibei.osm.pbf` 裁剪场景原点附近约 500×500 m，用于小范围调试（非流水线步骤）。 |

---

## 五、库代码（一般不直接当脚本跑）

`tools/cityusd/` 是被上述入口调用的库：

| 路径 | 用途 |
|------|------|
| `cityusd/pipeline/` | 流水线各 step：`resolve_extent`、`terrain`、`osm_city_usd`、`nav_pgm`、`assemble_world` 等 |
| `cityusd/pipeline/schema.py` | 加载场景/`configs/default` 配置、JSONC 解析 |
| `cityusd/osm_parse.py` / `roads.py` / `buildings.py` / … | OSM 解析与几何构建 |
| `cityusd/pgm.py` / `nav_polys.py` | PGM 栅格化与导航多边形 |
| `cityusd/rasters.py` / `dem_nature.py` | DEM/正射与 nature 坡度 |
| `cityusd/package.py` / `usd_write.py` | Scene Package / USD 写出 |
| `cityusd/scene_layout.py` | `SceneData/{id}/…` 路径约定 |

调试用模块示例：`nav_align_overlay.py`（PGM↔USD 对齐叠加，仅 debug，不进 World）。

---

## 六、怎么选

```text
要出完整 UE 场景包？
  → build_scene_pipeline.py --scene <id>

只要改某一层配置再重跑？
  → 改 SceneData/<id>/input/config/*.json
  → build_scene_pipeline.py --scene <id> --only <step>

只要换分辨率/只留道路/MPPI 代价？
  → 第三节独立脚本（在已有 CostMap 上做变体）

只要补贴图素材？
  → download_facade_inbox.py
```
