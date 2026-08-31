"""Map OSM tags / building height to package texture keys."""

from __future__ import annotations

ROAD_TEXTURE_BY_HIGHWAY = {
    "motorway": "highway",
    "trunk": "expressway",
    "primary": "national",
    "secondary": "provincial",
    "tertiary": "county",
    "residential": "asphalt",
    "unclassified": "asphalt",
    "living_street": "asphalt",
    "service": "cement",
    "footway": "path",
    "path": "path",
    "pedestrian": "pavement",
    "steps": "pavement",
    "cycleway": "pavement",
    "bridleway": "path",
    "track": "dirt",
    "construction": "dirt",
    "proposed": "dirt",
    "corridor": "pavement",
    "raceway": "asphalt",
    "busway": "asphalt",
    "junction": "asphalt",
}

ROAD_DISPLAY_RGB = {
    "highway": (0.12, 0.12, 0.14),
    "expressway": (0.16, 0.16, 0.18),
    "national": (0.18, 0.18, 0.20),
    "provincial": (0.22, 0.22, 0.22),
    "county": (0.24, 0.24, 0.23),
    "asphalt": (0.28, 0.28, 0.28),
    "cement": (0.45, 0.45, 0.42),
    "dirt": (0.45, 0.32, 0.18),
    "path": (0.55, 0.48, 0.32),
    "pavement": (0.52, 0.50, 0.46),
    "gravel": (0.40, 0.38, 0.34),
}

FACADE_DISPLAY_RGB = {
    "low": (0.72, 0.58, 0.42),
    "mid": (0.78, 0.74, 0.68),
    "high": (0.62, 0.68, 0.74),
    "tower": (0.55, 0.62, 0.72),
}

# Taipei flat roofs: dark gray waterproof membrane / concrete / metal sheet.
ROOF_DISPLAY_RGB = (0.28, 0.29, 0.30)

FACADE_VARIANT_COUNT = 16
ROOF_VARIANT_COUNT = 12
FACADE_VARIANTS = {"low": 16, "mid": 12, "high": 8, "tower": 8}
FACADE_TILE_FLOORS = {"low": 3, "mid": 8, "high": 10, "tower": 14}
FACADE_TILE_UV_SCALE = 12.0
FACADE_SHEET_WIDTH_M = {"low": 12.0, "mid": 16.0, "high": 20.0, "tower": 24.0}
LOW_SHOP_VARIANTS = 8


def road_texture_key(highway: str) -> str:
    hwy = (highway or "").strip().lower()
    return ROAD_TEXTURE_BY_HIGHWAY.get(hwy, "asphalt")


def facade_band(height_m: float) -> str:
    """1–3 low, 4–8 mid (masonry), 9–15 high, 16+ tower. Height is floors×3 m."""
    floors = max(1, int(round(float(height_m) / 3.0)))
    if floors <= 3:
        return "low"
    if floors <= 8:
        return "mid"
    if floors <= 15:
        return "high"
    return "tower"


def facade_tile_floors(band: str) -> int:
    return int(FACADE_TILE_FLOORS.get(band, 3))


def facade_tile_uv_scale() -> float:
    """How many times larger a tileable facade module is on the wall (less dense windows)."""
    return float(FACADE_TILE_UV_SCALE)


def facade_sheet_width_m(band: str) -> float:
    """World width in meters that one unique-sheet photo should cover."""
    return float(FACADE_SHEET_WIDTH_M.get(band, 12.0))


def road_display_rgb(key: str) -> tuple[float, float, float]:
    return ROAD_DISPLAY_RGB.get(key, ROAD_DISPLAY_RGB["asphalt"])


def facade_display_rgb(band: str) -> tuple[float, float, float]:
    return FACADE_DISPLAY_RGB.get(band, FACADE_DISPLAY_RGB["mid"])


def roof_display_rgb() -> tuple[float, float, float]:
    return ROOF_DISPLAY_RGB


def facade_variant_count(band: str) -> int:
    return int(FACADE_VARIANTS.get(band, FACADE_VARIANT_COUNT))


def facade_variant(osm_id: int, band: str = "mid", tags: dict | None = None) -> int:
    n = facade_variant_count(band)
    oid = abs(int(osm_id))
    if band == "low":
        from cityusd.inbox_bind import is_shop_building

        n_shop = min(LOW_SHOP_VARIANTS, n)
        if is_shop_building(tags):
            return oid % n_shop
        return n_shop + (oid % max(1, n - n_shop))
    return oid % n


def roof_variant(osm_id: int) -> int:
    return abs(int(osm_id) // 7) % ROOF_VARIANT_COUNT


def facade_material_path(band: str, osm_id: int, tags: dict | None = None) -> str:
    return f"/World/Looks/Facade_{band}_{facade_variant(osm_id, band, tags)}"


def roof_material_path(osm_id: int) -> str:
    return f"/World/Looks/Roof_{roof_variant(osm_id)}"


def looks_path(kind: str) -> str:
    """USD material prim path under /World/Looks."""
    return f"/World/Looks/{kind}"
