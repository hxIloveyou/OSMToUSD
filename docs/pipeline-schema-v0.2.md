# Scene Package Pipeline — Schema v0.2

> **Superseded by [pipeline-schema-v0.3.md](pipeline-schema-v0.3.md)** for nav2 layout.

CityUsd / USDManager 共用的 **Scene Package 构建契约**。  
实现入口：`tools/build_scene_pipeline.py`（M0–M4 已实现）。

## 设计原则

1. **Pipeline 管编排**（跑什么、顺序、skip/resume）；**Step config 管细节**（`configs/*.json`）。
2. **粗粒度 Step**：OSM→USD 一步；terrain / nav_pgm / osm_labels 各一步。
3. **共享契约**：`extent.json`（`resolve_extent` 唯一写入）。
4. **包布局**：`cityusd_v1`（与 `cityusd/package.py` 的 `WORLD_SUBLAYERS` 一致）。
5. **Preset 继承**：`extends:` 合并 YAML，城市差异不进 core schema。

## 目录布局（cityusd_v1）

```
ScenePackages/<scene_id>/
  pipeline.yaml
  manifest.json
  meta.json
  extent.json
  World_<scene_id>.usda

  terrain/          # terrain step
  nav/              # nav_pgm step
  layers/           # osm_city_usd + assemble
  catalog/          # osm_labels（分片）
  overlay/
  configs/          # 运行时生成的 step 配置快照
```

## Step 列表

| Step | 默认 | 说明 |
|------|------|------|
| `resolve_extent` | on | 空间合同 → `extent.json` |
| `terrain` | on | DEM/ortho → UTM + UE heightmap |
| `osm_city_usd` | on | OSM → `city_*.usdc` |
| `osm_labels` | on | 分片 catalog + API |
| `nav_pgm` | on | OSM 占据栅格（v0.2 仅 OSM） |
| `overlay` | on | AssetLibrary 装备层 |
| `assemble_world` | on | World subLayers + meta |
| `package_zip` | on | 可选 zip |

## resolve_extent

### `frame.extent.mode`

| mode | 行为 |
|------|------|
| `explicit` | 使用 `frame.extent.explicit` |
| `osm_bbox` | 仅 OSM 外包框 |
| `dem_bounds` | 仅 DEM（± ortho 交集） |
| `auto` | 见下 |

### `auto` 与 OSM / terrain 关系

| 关系 | 行为 |
|------|------|
| **包含** | `extent = 较小者`（如 DEM⊂OSM → 用 DEM 框，OSM clip） |
| **交叉** | **WARN** + `extent = 交集`，继续构建 |
| **相离** | 默认 **FAIL**；`allow_disjoint: true`（debug preset）可仅 OSM |

### 产出 `extent.json`

含 `wgs84`、`local_m`、`origin_wgs84`、`utm_epsg`、`warnings`、`resolution.osm_vs_terrain`。

## osm_labels（v0.2）

- **分片网格与 LOD0 对齐**（默认 `cell_size_m: 200`）。
- **`compose_into_world: false`** — 不 subLayer 进 World。
- **运行时 API** + 本地 shard 缓存（UE 半在线）。
- 输出：`catalog/index/shard_manifest.json`、`catalog/shards/lod0_{ix}_{iy}.json`。
- Mesh prim 带 `osm_id`、`catalog_shard`。

## nav_pgm（v0.2）

- **仅依赖 OSM**（`sources.occupancy: osm`）。
- 后续可在 `configs/nav_pgm_*.json` 增加 `dem` 源，不改 pipeline 结构。
- **对齐预览（debug）**：默认写 `debug/nav_align/`（彩色 PNG + 半透明平面 USDA）。
  - **不**加入 `World_*.usda` subLayers。
  - 生产关闭：`align_overlay.enabled: false`；`package_zip` 已排除 `debug/**`。
  - 查看：在 UE 中打开 World 后再打开 `debug/nav_align/nav_align_overlay.usda`。
- **绘制优先级**：先 occupied（建筑/水），再 free（motor 道路）——路面与 footprint 重叠时保持可通行。
- **建筑**：默认 `simple_buildings: false`（footprint 会挖道路）；`true` 仅用于快速调试。

## scene.id

- 空 → `{id_pattern}`，默认 `taibei_ue_{YYYYMMDD_HHMMSS}`。

## CLI

```bash
cd CityUsd
set PYTHONPATH=tools

python tools/build_scene_pipeline.py --preset taibei_ue
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml --only resolve_extent,terrain
python tools/build_scene_pipeline.py --config examples/taibei_ue.pipeline.yaml --resume
python tools/build_scene_pipeline.py --preset taibei_debug --set scene.id=taibei_debug_manual
```

## 文件位置

| 路径 | 说明 |
|------|------|
| `examples/*.pipeline.yaml` | 可运行示例 |
| `presets/*.yaml` | 城市/场景 preset |
| `configs/*.json` | Step 外置配置（`config_ref`） |
| `tools/cityusd/pipeline/` | 实现库 |
| `tools/build_scene_pipeline.py` | CLI |

## 实现阶段

| 阶段 | 内容 |
|------|------|
| **M0（当前）** | `resolve_extent` + CLI + manifest + step stub |
| **M1（当前）** | `terrain` — DEM/ortho → UTM GeoTIFF + UE 16-bit heightmap + alignment.json |
| **M2（当前）** | `osm_city_usd` — 调用 `build_city_usd --pipeline-mode` → `city_*.usdc` |
| **M3（当前）** | `nav_pgm`（OSM 占据栅格）+ `osm_labels`（LOD0 分片 catalog） |
| **M4（当前）** | `overlay`（空装备层）+ `assemble_world`（World/meta）+ `package_zip` |

## 已拍板决策（2026-08-31）

- 布局：**cityusd_v1**
- 默认开启：**terrain + nav_pgm + osm_labels**
- scene.id：**taibei_ue_{timestamp}**
- 大配置：**config_ref 外置**
- extent 交叉：**warn + 交集**；相离：**fail**（debug 可 `allow_disjoint`）
