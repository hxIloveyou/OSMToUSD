"""Nav2 output layout constants (pipeline schema v0.3)."""

from __future__ import annotations

NAV2_ROOT = "nav2"
NAV2_CONNECTED = "nav2/connected"
NAV2_VARIANTS = "nav2/variants"
NAV2_NATURE = "nav2/nature"
NAV2_DEM = "nav2/dem"

NAV2_CONNECTED_PGM = f"{NAV2_CONNECTED}/map.pgm"
NAV2_CONNECTED_COST = f"{NAV2_CONNECTED}/cost.pgm"
NAV2_CONNECTED_MAP_LOCAL = f"{NAV2_CONNECTED}/map_local.yaml"
NAV2_CONNECTED_MAP_UTM = f"{NAV2_CONNECTED}/map.yaml"
NAV2_CONNECTED_VALHALLA = f"{NAV2_CONNECTED}/valhalla_origin.yaml"
NAV2_CONNECTED_META = f"{NAV2_CONNECTED}/map_meta.json"
