"""Tests for nav2 nature DEM export."""

from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import from_origin

from cityusd.bmp_slope_occupancy import build_slope_occupancy
from cityusd.dem_nature import build_nav2_nature_from_dem_utm, elevation_to_bmp
from cityusd.types import ExtentM, Origin


def test_elevation_to_bmp_and_slope(tmp_path):
    elev = np.linspace(100, 120, 100, dtype=np.float32).reshape(10, 10)
    gray, center, scale = elevation_to_bmp(elev)
    assert gray.shape == (10, 10)
    assert center > 0
    assert scale > 0
    occ = build_slope_occupancy(gray, 10.0, scale, 0.35)
    assert occ.shape == (10, 10)
    assert int((occ == 254).sum()) > 0


def test_build_nav2_nature_from_dem_utm(tmp_path):
    dem_path = tmp_path / "dem_utm.tif"
    elev = np.full((20, 20), 150.0, dtype=np.float32)
    transform = from_origin(1000.0, 2000.0, 10.0, 10.0)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float32",
        transform=transform,
        crs="EPSG:32651",
    ) as ds:
        ds.write(elev, 1)

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    extent = ExtentM(0.0, 0.0, 200.0, 200.0)
    origin = Origin(lon=121.0, lat=25.0, height_m=0.0, epsg=32651)
    result = build_nav2_nature_from_dem_utm(
        dem_path,
        pkg,
        extent=extent,
        origin=origin,
        name="testdem",
    )
    assert (pkg / "nature" / "testdem.bmp").is_file()
    assert (pkg / "nature" / "testdem.pgm").is_file()
    assert (pkg / "nature" / "nature_bmp.yaml").is_file()
    assert result["free_px"] >= 0
