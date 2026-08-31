# OSM 城市场景 Scene Package 生成规范

| 项 | 值 |
|----|-----|
| 版本 | 1.0 |
| 日期 | 2026-08-24 |
| 状态 | 已定稿（待实现） |
| 工作目录 | `E:/UEWork/ROS2Test/CityUsd/` |
| 对齐参考 | 既有 Scene Package 约定（`World_*.usda` + `layers/` + `meta.json`，规范 1.3 风格） |

---

## 0. 目标与非目标

**目标：** 从 `CityUsd/data/` 中的 OSM（必选）、DEM、影像、可选资产库，生成一套可被 UE UsdStage 打开的 Scene Package：建筑 / 道路 / 水系 / 植被、带 LOD、中国道路标线与路口箭头、路牌、消重叠、与 USD 对齐的 16 位高度图与正射 PNG、以及同坐标系的 Nav2 PGM。风格靠近 CityEngine，资产不全时用占位与程序化网格，不阻塞生成。

**非目标（本版本不做）：**

- 建筑 / 道路贴 DEM（全部铺在 Z=0）。
- 消费场景描述 JSON 的 overlay 摆件（接口预留，无文件则空层）。
- 全城逐棵高精度树 / 高精度路灯 GLB（只用占位 + PointInstancer，便于日后换模）。
- 调用工作区外 USDManager 旧脚本作为运行时依赖（本目录自包含）。

---

## 1. 输入

根路径：`CityUsd/data/`。子目录可空；扫描时也接受直接放在 `data/` 根下的文件。

| 目录 / 文件 | 必选 | 格式 | 用途 |
|-------------|------|------|------|
| `data/osm/` | **是** | `.osm` 或 `.osm.pbf` | 建筑、道路、水系、植被、路名 |
| `data/dem/` | 否 | GeoTIFF | 生成 16 位高度图 + JSON |
| `data/imagery/` | 否 | GeoTIFF / 大图 PNG | 生成对齐正射 PNG + JSON |
| `data/assets/` | 否 | 目录或 `catalog.json` | 材质 / 网格；损坏则忽略 |
| `data/descriptions/*.json` | 否 | 见 §8 | 预留 overlay；本版本不实例化 |

多文件时：OSM 取第一个 `.osm.pbf`，若无则取第一个 `.osm`。DEM / 影像各取覆盖范围最大的一份栅格。

---

## 2. 交付物

```text
CityUsd/
  data/                          # 输入（用户放置）
  tools/                         # 生成脚本（实现阶段创建）
  output/ScenePackage/
    meta.json
    sources_manifest.json
    assets_used.json
    World_<scene_id>.usda        # 薄入口
    layers/
      environment.usda
      terrain.usda
      nav.usda                   # PGM / 高度图 / 影像路径引用
      base_osm.usdc              # 城市场景几何
    overlay/
      equipment.usda             # 空占位（描述 JSON 预留）
      infrastructure.usda
      obstacles_static.usda
      obstacles_dynamic.usda
      props.usda
    terrain_src/
      heightmap_16bit.png
      heightmap_meta.json
      ortho.png
      ortho_meta.json
    nav/
      map.pgm
      map.yaml
      map_meta.json
    textures/
    models/
      prototypes/                # 树 / 灯 / 路牌占位
```

禁止只交一个孤立 `.usdc` 作为正式产物。入口必须是 `World_*.usda`，`defaultPrim = World`。

---

## 3. 坐标系与单位

| 项 | 约定 |
|----|------|
| 权威投影 | UTM，EPSG 由原点纬度决定（台北区域为 **EPSG:32651**） |
| 原点 | DEM 地理中心；无 DEM 时用 OSM bbox 中心。写入 `meta.json` 的 `origin_wgs84` |
| USD 轴 | +X 东，+Y 北，+Z 上 |
| USD 单位 | `metersPerUnit = 0.01`（厘米），`upAxis = Z` |
| 高度图 / 影像 / PGM 的平面坐标 | **米**（同一原点），不要用厘米 |
| 建筑 / 道路 / 水系 / 植被 Z | **0**（可加厘米级层偏移防 z-fight，见 §6.4） |

高度图与正射影像：北向上；像素 (0,0) = 地理**西北**角。  
PGM：北向上；ROS `map.yaml` 的 `origin` = 栅格**西南**角在局部米坐标（ROS map_server 将文件第一行视为图像顶）。

四至 `extent_m`：有 DEM 用 DEM 矩形；无 DEM 用 OSM bbox。高度图、正射、PGM、USD 局部范围使用**同一** `extent_m` 与同一原点。

---

## 4. 生成流程

```text
1. 扫描 data/，定位 OSM（缺则失败退出）
2. 确定 origin + extent
3. DEM → terrain_src/heightmap_16bit.png + heightmap_meta.json（无 DEM 则跳过文件，层仍存在）
4. 影像 → 重投影到同一矩形 → ortho.png + ortho_meta.json
5. OSM 解析 → 道路分级/标线/箭头/路牌 → 建筑挤出+LOD → 水系/植被面
6. 消重叠（§6.4）
7. PointInstancer 树 / 路灯占位（§7）
8. 写 base_osm.usdc + environment + terrain + nav 层
9. 写空 overlay 层
10. OSM → nav/map.pgm + map.yaml（§9）
11. 写 World_*.usda、meta.json、sources_manifest.json、assets_used.json
```

描述 JSON：本版本只记录路径到 `sources_manifest`（若存在），**不**摆放装备/障碍。

---

## 5. USD Prim 树

入口 `World_<scene_id>.usda` 仅含 stage 元数据与 `subLayers`（自下而上）：

1. `layers/environment.usda`
2. `layers/terrain.usda`
3. `layers/nav.usda`
4. `layers/base_osm.usdc`
5. `overlay/equipment.usda`
6. `overlay/infrastructure.usda`
7. `overlay/obstacles_static.usda`
8. `overlay/obstacles_dynamic.usda`
9. `overlay/props.usda`

```text
/World
  /Environment
  /Terrain                 # 引用高度图/影像，可选对齐参考平面（默认不可见）
  /Nav                     # 引用 PGM/YAML
  /City
      /Roads
      /Buildings           # 子 Mesh 名 LOD0/LOD1/LOD2
      /Water
      /Vegetation          # Prototypes + PointInstancer
      /StreetFurniture     # 路灯 Instancer；路牌（字不同可独立）
  /Overlay
      /Equipment
      /Infrastructure
      /ObstaclesStatic
      /ObstaclesDynamic
      /Props
```

OSM 要素 customData 至少包含：`osm:id`、主要 tag（如 `highway`、`building`、`name`）。

---

## 6. OSM 几何

### 6.1 道路宽度

有 OSM `width`（米）则用之；否则用 `lanes × 3.5m`（若有 `lanes`）；否则按下表：

| highway | 默认宽度 (m) |
|---------|----------------|
| motorway | 22 |
| trunk | 16 |
| primary | 12 |
| secondary | 9 |
| tertiary | 7 |
| residential | 6 |
| service | 4 |
| footway / path | 2 |
| 其他 | 5 |

几何：中心线 buffer 成面。机动车道参与 PGM 空闲；footway / path 不进入 PGM 空闲。

### 6.2 中国道路标线（GB 5768 惯例）

标线为路面之上的窄带 mesh 或贴花，**不**用一张纹理铺整条路来冒充标线。

| OSM 类型 | 中心线 | 车道线 | 边缘线 |
|----------|--------|--------|--------|
| motorway / trunk（分行或 ≥4 车道） | 中央分隔或双黄实线 | 白虚线；路口前改白实线 | 白实线 |
| primary | 双黄实线 | 白虚线 | 白实线 |
| secondary | 宽度 ≥9m 双黄实线，否则单黄实线 | 白虚线 | 白实线 |
| tertiary | 单黄虚线 | 较宽才画白虚线 | 可选白实线 |
| residential | 宽度 ≥6m 单白虚线，否则不画 | 无 | 无 |
| service / footway | 无 | 无 | 无 |

补充：

- 双向两车道禁止越线：单黄实线；允许超车：单黄虚线（tertiary 默认按允许超车的虚线）。
- 路口进口 15–30m：车道线改白实线 + 停止线 + 单向导向箭头（禁用对向箭头贴图）。
- 中心线双黄用于对向隔离；白线用于同向车道与路缘。

### 6.3 路牌

有 `name` 或 `name:zh` / `name:en` 的机动车道路段：沿路右侧每隔 80–120m 放一块程序化路牌（板 + 路名贴图）。路名不同则不进 HISM。LOD2 距离关闭路牌。

### 6.4 消重叠（优先级从高到低）

1. 道路 vs 道路：高等级切割低等级；交叉口用 junction 面替换重叠条带。
2. 建筑 vs 道路：建筑轮廓差集减去道路 polygon。
3. 植被 / 水系 vs 道路与建筑：差集去掉被覆盖部分。
4. 层偏移仅作保险（局部米）：水系 -0.02、植被 +0.05、道路 +0.08、建筑 +0.04，再乘 100 写入厘米。主手段是几何裁剪。

### 6.5 建筑

- 高度：`height` → 否则 `building:levels × 3.0m` → 否则 10m。
- LOD0：cell 200m，`switch_distance_m = 0`（近景），立面分带纹理。
- LOD1：cell 800m，`switch_distance_m = 1500`。
- LOD2：cell 3200m，`switch_distance_m = 6000`，合并材质。
- 距离单位：米。每个建筑格网父 prim 下三个子 Mesh，名称固定为 `LOD0`、`LOD1`、`LOD2`，供 UE USD 导入识别为同一资产的 LOD。切换距离写入父 prim 的 customData（`switch_distance_m`），并换算成厘米 extents 供 Stage 使用。

### 6.6 水系与植被面

- `natural=water`、`water=*`、`landuse=reservoir` 等面 → 水面 mesh。
- `waterway=river/stream/canal` 线 → 按宽度 buffer（默认河 8m、溪 3m、渠 5m）。
- `landuse=grass/forest/meadow`、`leisure=park`、`natural=wood` → 植被面 + 纹理。
- 单棵 `natural=tree` 进入 PointInstancer，不把全城 landuse 打成单树。

---

## 7. 植被 / 路灯：占位 + PointInstancer（UE HISM）

USD 使用 `UsdGeomPointInstancer`。UE UsdStage / USD 导入将其收成 HISM。

```text
/City/Vegetation/Prototypes/TreePlaceholder
/City/Vegetation/I_Trees
/City/StreetFurniture/Prototypes/LampPlaceholder
/City/StreetFurniture/I_Lamps
```

- 每种原型一个 Instancer：`protoIndices`、`positions`、`orientations`、`scales`。
- 占位网格极简（树：圆柱+圆锥/球；灯：杆+箱），写入 `models/prototypes/`。
- 日后换模：只改 Prototype 的 reference/payload 指向新 GLB，实例变换不变。
- 路灯：在 primary 及以上道路两侧按 25–35m 间距放置；residential 可选更稀或不放。
- LOD2 远距：关闭 Instancer 或只保留植被面。
- `meta.json`：`vegetation_instancer: true`，`lamp_instancer: true`，`prototype_swap: true`。

---

## 8. 描述 JSON（预留，本版本不消费摆件）

路径：`data/descriptions/*.json` 或未来 CLI `--description`。

约定字段（以后实现）：

```json
{
  "spec_version": "1.1",
  "scene_id": "optional",
  "placements": [
    {
      "id": "car_01",
      "asset_id": "vehicle_sedan",
      "class": "dynamic",
      "pose": { "x_m": 10, "y_m": 0, "z_m": 0, "yaw_deg": 0 }
    }
  ]
}
```

`class` 映射：`dynamic` → ObstaclesDynamic；`static` 障碍 → ObstaclesStatic；装备 → Equipment；其余 → Props。  
本版本：有文件则在 `sources_manifest` 登记，overlay prim 仍为空。无文件同样写空 overlay 层，不改入口结构。

---

## 9. 地形、影像、PGM

### 9.1 16 位高度图

- `terrain_src/heightmap_16bit.png`：16 位灰度，北向上。
- `zmin_m` / `zmax_m` 写入 JSON；像素 0 → zmin，65535 → zmax。
- 像素边长：将 DEM 重采样到最长边 **2049**（奇数，便于 UE Landscape）；`meters_per_pixel = extent_m / (size_px - 1)`。
- `heightmap_meta.json` 必填：`size_px`、`zmin_m`、`zmax_m`、`origin_wgs84`、`utm_origin`、`extent_m`（east, north）、`meters_per_pixel`、`crs_epsg`。

无 DEM：不写 PNG，JSON 可省略；`terrain.usda` 仍存在，customData 标明缺失。

### 9.2 正射影像

- 重投影到与高度图同一矩形后输出 `ortho.png`（最长边默认 8192，可配，下限 4096）。
- `ortho_meta.json` 与高度图共用 `origin_wgs84`、`extent_m`、`crs_epsg`。

### 9.3 PGM（Nav2）

| 像素 | 含义 | 来源 |
|------|------|------|
| 0 | 占用 | 建筑、水面 |
| 254 | 空闲 | 机动车 `highway` 按宽度 buffer |
| 205 | 未知 | 其余 |

- 默认分辨率 **1.0 m/px**（可配）。
- 四至与高度图/影像相同；无 DEM 时用 OSM bbox。
- `map.yaml`：`resolution`、`origin: [x_sw_m, y_sw_m, 0]`、`negate: 0`、`occupied_thresh: 0.65`、`free_thresh: 0.196`。
- `map_meta.json` 与 `heightmap_meta.json` 字段对齐，并含 `range_source`: `dem` 或 `osm_bbox`。
- 标线、路牌、路灯不写入 PGM。

`layers/nav.usda` 与 `layers/terrain.usda` 用 customData 保存相对路径（`./nav/map.pgm`、`./terrain_src/heightmap_16bit.png` 等），不把栅格像素嵌进 USD 几何。

---

## 10. 资产补充

查找顺序：`data/assets` 可用项 → 程序化网格/贴图 → 包内自带占位。  
不依赖包外绝对路径。库文件损坏则跳过并记入 `assets_used.json`（`source: generated` 或 `source: library`）。

路面、立面、标线、水面、草地以程序化或 CityEngine 风格瓦片为主。树 / 灯用 §7 占位。

---

## 11. 失败与部分成功

| 情况 | 行为 |
|------|------|
| 无 OSM | 退出码非 0，不写半包 |
| 无 DEM / 无影像 / 无描述 | 警告，对应产物跳过，其余继续 |
| 单要素三角化失败 | 跳过该要素，计数写入日志 |
| 资产库损坏 | 忽略坏文件，改占位 |

---

## 12. 验收清单

- [ ] `World_*.usda` 可被 UsdStage 打开：`defaultPrim=/World`，厘米，Z-up。
- [ ] 建筑与道路在 Z=0（允许 §6.4 厘米级偏移）。
- [ ] 高度图、正射、PGM、USD 共用原点与 `extent_m`。
- [ ] 道路按类型有双黄 / 单黄 / 白虚 / 白实及路口单向箭头。
- [ ] 建筑 LOD0/1/2 可切换。
- [ ] 树与路灯为 `UsdGeomPointInstancer`。
- [ ] 无描述 JSON 时 overlay 层存在但为空。
- [ ] `nav/map.yaml` 与 USD 叠加时：建筑落在占用，机动车道落在空闲。
- [ ] `meta.json` 含 crs、原点、层路径、LOD、instancer 标志、PGM 路径。

---

## 13. CLI（实现阶段）

```text
python tools/build_city_usd.py --data CityUsd/data --output CityUsd/output/ScenePackage
```

`scene_id` 默认 = OSM 文件名 stem + `_` + 日期 `YYYYMMDD`。  
可选：`--pgm-resolution 1.0`、`--ortho-max-dim 8192`、`--scene-id <id>`。  
`--description` 本版本只登记，不摆件。
