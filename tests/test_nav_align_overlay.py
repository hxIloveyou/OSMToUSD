"""Tests for debug nav align overlay (not composed into World)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom

from cityusd.nav_align_overlay import write_nav_align_overlay
from cityusd.pgm import FREE, OCCUPIED, UNKNOWN, _write_pgm
from cityusd.types import ExtentM


def test_nav_align_overlay_writes_debug_only(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    nav = pkg / "nav"
    nav.mkdir(parents=True)
    grid = np.full((40, 60), UNKNOWN, dtype=np.uint8)
    grid[10:30, 20:40] = FREE
    grid[5:15, 5:15] = OCCUPIED
    pgm = nav / "map.pgm"
    _write_pgm(pgm, grid)
    meta = nav / "map_meta.json"
    meta.write_text(
        '{"coverage_m":{"west":-30,"south":-20,"east":30,"north":20,'
        '"width":60,"height":40},"size_px":[60,40]}\n',
        encoding="utf-8",
    )
    extent = ExtentM(west=-30, south=-20, east=30, north=20)

    outs = write_nav_align_overlay(
        pkg,
        map_pgm=pgm,
        map_meta_path=meta,
        extent=extent,
        enabled=True,
        max_preview_side=64,
    )
    assert any("debug/nav_align/nav_align_overlay.usda" in o for o in outs)
    usda = pkg / "debug" / "nav_align" / "nav_align_overlay.usda"
    png = pkg / "debug" / "nav_align" / "align_preview.png"
    assert usda.is_file()
    assert png.is_file()
    assert (pkg / "debug" / "nav_align" / "README.txt").is_file()

    stage = Usd.Stage.Open(str(usda))
    plane = stage.GetPrimAtPath("/World/DebugNavAlign/AlignPlane")
    assert plane.IsValid()
    assert plane.IsA(UsdGeom.Mesh)
    custom = stage.GetPrimAtPath("/World/DebugNavAlign").GetCustomData()
    assert custom.get("production") in (False, "false")

    assert write_nav_align_overlay(
        pkg, map_pgm=pgm, map_meta_path=meta, extent=extent, enabled=False
    ) == []
