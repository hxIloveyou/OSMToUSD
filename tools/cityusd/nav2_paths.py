"""Nav / CostMap 2D output layout (relative to SceneData/{id}/output/{id}-CostMap/2D)."""
# 中文说明：CostMap/2D 相对路径常量（connected/variants/nature）。

from __future__ import annotations

# All paths are relative to {scene_id}-CostMap/2D/
COSTMAP_2D_CONNECTED = "connected"
COSTMAP_2D_VARIANTS = "variants"
COSTMAP_2D_NATURE = "nature"
COSTMAP_2D_DEM = "dem"

# Backward-compatible aliases (old nav2/* names → CostMap/2D/*)
NAV2_ROOT = ""  # CostMap/2D is the root
NAV2_CONNECTED = COSTMAP_2D_CONNECTED
NAV2_VARIANTS = COSTMAP_2D_VARIANTS
NAV2_NATURE = COSTMAP_2D_NATURE
NAV2_DEM = COSTMAP_2D_DEM

NAV2_CONNECTED_PGM = f"{NAV2_CONNECTED}/map.pgm"
NAV2_CONNECTED_COST = f"{NAV2_CONNECTED}/cost.pgm"
NAV2_CONNECTED_MAP_LOCAL = f"{NAV2_CONNECTED}/map_local.yaml"
NAV2_CONNECTED_MAP_UTM = f"{NAV2_CONNECTED}/map.yaml"
NAV2_CONNECTED_VALHALLA = f"{NAV2_CONNECTED}/valhalla_origin.yaml"
NAV2_CONNECTED_META = f"{NAV2_CONNECTED}/map_meta.json"
