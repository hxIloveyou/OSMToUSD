from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Origin:
    lon: float
    lat: float
    height_m: float
    epsg: int  # e.g. 32651


@dataclass(frozen=True)
class ExtentM:
    west: float   # local meters, min X
    south: float  # min Y
    east: float   # max X
    north: float  # max Y

    @property
    def width(self) -> float:
        return self.east - self.west

    @property
    def height(self) -> float:
        return self.north - self.south

    def to_json(self) -> dict:
        """west/south/east/north are min/max; width/height are derived."""
        return {
            "west": self.west,
            "south": self.south,
            "east": self.east,
            "north": self.north,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class RasterMeta:
    size_px: Tuple[int, int]
    zmin_m: Optional[float]
    zmax_m: Optional[float]
    origin: Origin
    utm_origin: Tuple[float, float]
    extent_m: ExtentM
    meters_per_pixel: Tuple[float, float]
    crs_epsg: int
    range_source: str  # "dem" | "osm_bbox"


LAYER_Z_M = {"water": -0.02, "vegetation": 0.05, "roads": 0.08, "buildings": 0.04}
CM_PER_M = 100.0
