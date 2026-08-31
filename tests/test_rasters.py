import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from cityusd.crs import make_origin, extent_from_lonlat_bbox
from cityusd.rasters import write_heightmap


def test_heightmap_written(tmp_path):
    tif = tmp_path / "dem.tif"
    arr = np.linspace(10.0, 40.0, 32 * 32, dtype=np.float32).reshape(32, 32)
    transform = from_origin(118.999, 36.002, 0.0001, 0.0001)
    with rasterio.open(
        tif, "w", driver="GTiff", height=32, width=32, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(arr, 1)
    origin = make_origin(119.0006, 36.0004)
    extent = extent_from_lonlat_bbox(118.999, 35.9988, 119.0022, 36.002, origin)
    meta = write_heightmap(tif, origin, extent, tmp_path / "h.png", tmp_path / "h.json")
    assert meta.size_px[0] <= 2049 and meta.size_px[1] <= 2049
    assert meta.zmin_m < meta.zmax_m
    assert (tmp_path / "h.png").exists()
    payload = json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))
    assert payload["crs_epsg"] == origin.epsg
    from cityusd.rasters import write_terrain_alignment

    align = write_terrain_alignment(
        tmp_path / "alignment.json",
        scene_id="tiny",
        origin=origin,
        extent=extent,
        heightmap_rel="./h.png",
        heightmap_meta_path=tmp_path / "h.json",
    )
    ap = json.loads(align.read_text(encoding="utf-8"))
    assert ap["usd"]["meters_per_unit"] == 0.01
    assert ap["usd"]["axes"]["z"] == "up"
    assert ap["heightmap"]["sampling"] == "vertex"
    assert ap["extent_usd_cm"]["width"] == payload["extent_m"]["width"] / 0.01
    assert "decode_z_m" in ap["heightmap"]
    pgm_meta = tmp_path / "map_meta.json"
    pgm_meta.write_text(
        json.dumps(
            {
                "size_px": [10, 8],
                "meters_per_pixel": [1.0, 1.0],
                "coverage_m": {
                    "west": payload["extent_m"]["west"],
                    "south": payload["extent_m"]["south"],
                    "east": payload["extent_m"]["west"] + 10.0,
                    "north": payload["extent_m"]["south"] + 8.0,
                    "width": 10.0,
                    "height": 8.0,
                },
                "cost_values": {"free": 0, "lethal": 254, "unknown": 255},
            }
        ),
        encoding="utf-8",
    )
    align2 = write_terrain_alignment(
        tmp_path / "alignment2.json",
        scene_id="tiny",
        origin=origin,
        extent=extent,
        heightmap_rel="./h.png",
        heightmap_meta_path=tmp_path / "h.json",
        pgm_rel="./nav/map.pgm",
        cost_rel="./nav/cost.pgm",
        pgm_meta_path=pgm_meta,
    )
    ap2 = json.loads(align2.read_text(encoding="utf-8"))
    assert ap2["costmap"]["cost_pgm"] == "./nav/cost.pgm"
    assert ap2["costmap"]["cost_values"]["lethal"] == 254
    assert ap2["shared_frame"]["extent_m_is_common"] is True
