"""Distance cull metadata on building meshes and PointInstancers."""

from __future__ import annotations

from pathlib import Path

from pxr import Usd, UsdGeom

from cityusd.cull import CULL_BUILDING_M, CULL_LAMP_END_M, CULL_LAMP_START_M
from cityusd.usd_write import (
    configure_stage,
    write_building_cell,
    write_point_instancer,
    write_preview_material,
)


def test_building_cell_writes_cull_custom_data(tmp_path: Path):
    path = tmp_path / "cull_bldg.usda"
    stage = configure_stage(path)
    write_preview_material(stage, "/World/Looks/Facade_mid_0", (0.7, 0.6, 0.5))
    write_preview_material(stage, "/World/Looks/Roof_0", (0.3, 0.3, 0.3))
    pts = [(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)]
    payload = (
        pts,
        [4],
        [0, 1, 2, 3],
        [(0.0, 0.0)] * 4,
        "/World/Looks/Facade_mid_0",
        (0.7, 0.6, 0.5),
        {"Walls": ([0], "/World/Looks/Facade_mid_0"), "Roof": ([], "/World/Looks/Roof_0")},
    )
    write_building_cell(stage, 0, 0, {"LOD0": payload}, suffix="mid_0")
    stage.GetRootLayer().Save()
    opened = Usd.Stage.Open(str(path))
    mesh = opened.GetPrimAtPath("/World/City/Buildings/c400_0_0_mid_0/LOD0")
    # cs==400 uses c400_ prefix; ix=iy=0
    if not mesh.IsValid():
        mesh = opened.GetPrimAtPath("/World/City/Buildings/c0_0_mid_0/LOD0")
    assert mesh.IsValid()
    cd = mesh.GetCustomData()
    assert float(cd.get("cull_distance_m") or 0) == float(CULL_BUILDING_M)
    assert float(cd.get("cull_distance_cm") or 0) == float(CULL_BUILDING_M) * 100.0
    assert cd.get("cull_mode") == "max_draw_distance"


def test_point_instancer_writes_hism_cull_custom_data(tmp_path: Path):
    path = tmp_path / "cull_inst.usda"
    stage = configure_stage(path)
    UsdGeom.Xform.Define(stage, "/World/City/Lamps")
    proto = "/World/City/Lamps/Proto"
    UsdGeom.Xform.Define(stage, proto)
    write_point_instancer(
        stage,
        "/World/City/Lamps/I_Lamps",
        proto,
        [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)],
        [0.0, 1.0],
        cull_custom_data={
            "cull_mode": "hism_instance_cull",
            "cull_start_m": CULL_LAMP_START_M,
            "cull_end_m": CULL_LAMP_END_M,
            "cull_start_cm": CULL_LAMP_START_M * 100.0,
            "cull_end_cm": CULL_LAMP_END_M * 100.0,
        },
    )
    stage.GetRootLayer().Save()
    opened = Usd.Stage.Open(str(path))
    inst = opened.GetPrimAtPath("/World/City/Lamps/I_Lamps")
    cd = inst.GetCustomData()
    assert cd.get("cull_mode") == "hism_instance_cull"
    assert float(cd["cull_start_m"]) == float(CULL_LAMP_START_M)
    assert float(cd["cull_end_m"]) == float(CULL_LAMP_END_M)
