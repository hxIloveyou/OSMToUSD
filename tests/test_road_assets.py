"""AssetLibrary road surface / arrow texture install."""

from __future__ import annotations

from pathlib import Path

from cityusd.inbox_bind import default_inbox_library, resolve_asset_library_root
from cityusd.proc_textures import ensure_scene_textures
from cityusd.road_assets import ARROW_KIND_ORDER, install_road_library_textures


def test_install_road_library_from_default_assets(tmp_path: Path) -> None:
    lib = default_inbox_library()
    if not (lib / "materials" / "roads").is_dir():
        return
    out = install_road_library_textures(tmp_path / "textures", lib)
    assert "asphalt" in out or "highway" in out
    assert out[next(iter(out))].is_file()
    assert any(f"arrow_{k}" in out for k in ARROW_KIND_ORDER)


def test_ensure_scene_textures_prefers_library(tmp_path: Path) -> None:
    lib = resolve_asset_library_root()
    if lib is None or not (lib / "materials" / "roads").is_dir():
        return
    written = ensure_scene_textures(tmp_path / "tex", library_dir=lib)
    assert written["highway"].is_file()
    assert written["arrow_straight"].is_file()
    assert written["arrow_left"].is_file()
    # Library asphalt should not be tiny procedural-only when Highway_D exists
    hwy = lib / "materials" / "roads" / "RoadSurfaces" / "T_RoadSurf_Asphalt_Highway_D.png"
    if hwy.is_file():
        assert written["highway"].stat().st_size >= hwy.stat().st_size * 0.5
