from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TIFF_SUFFIXES = {".tif", ".tiff"}
IMAGERY_SUFFIXES = {".tif", ".tiff", ".png"}


@dataclass
class FoundInputs:
    osm: Optional[Path]
    dem: Optional[Path]
    imagery: Optional[Path]
    assets_dir: Optional[Path]
    descriptions: list[Path]


def _find_osm(data_dir: Path) -> Optional[Path]:
    search_dirs: list[Path] = []
    osm_dir = data_dir / "osm"
    if osm_dir.is_dir():
        search_dirs.append(osm_dir)
    search_dirs.append(data_dir)

    for directory in search_dirs:
        pbf_files = sorted(directory.glob("*.osm.pbf"))
        if pbf_files:
            return pbf_files[0]
        osm_files = sorted(directory.glob("*.osm"))
        if osm_files:
            return osm_files[0]
    return None


def _collect_by_suffix(directory: Path, suffixes: set[str], recursive: bool) -> list[Path]:
    if not directory.is_dir():
        return []
    found: list[Path] = []
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    for path in iterator:
        if path.is_file() and path.suffix.lower() in suffixes:
            found.append(path)
    return found


def _largest_file(candidates: list[Path]) -> Optional[Path]:
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def _find_dem(data_dir: Path) -> Optional[Path]:
    dem_dir = data_dir / "dem"
    candidates = _collect_by_suffix(dem_dir, TIFF_SUFFIXES, recursive=True)
    if not candidates:
        candidates = _collect_by_suffix(data_dir, TIFF_SUFFIXES, recursive=False)
    return _largest_file(candidates)


def _find_imagery(data_dir: Path, dem: Optional[Path]) -> Optional[Path]:
    imagery_dir = data_dir / "imagery"
    candidates = _collect_by_suffix(imagery_dir, IMAGERY_SUFFIXES, recursive=True)
    if not candidates:
        candidates = _collect_by_suffix(data_dir, IMAGERY_SUFFIXES, recursive=False)
    if dem is not None:
        candidates = [p for p in candidates if p.resolve() != dem.resolve()]
    return _largest_file(candidates)


def _find_descriptions(data_dir: Path) -> list[Path]:
    desc_dir = data_dir / "descriptions"
    if not desc_dir.is_dir():
        return []
    return sorted(desc_dir.glob("*.json"))


def _find_assets_dir(data_dir: Path) -> Optional[Path]:
    assets = data_dir / "assets"
    return assets if assets.is_dir() else None


def scan_data_dir(data_dir: Path) -> FoundInputs:
    dem = _find_dem(data_dir)
    return FoundInputs(
        osm=_find_osm(data_dir),
        dem=dem,
        imagery=_find_imagery(data_dir, dem),
        assets_dir=_find_assets_dir(data_dir),
        descriptions=_find_descriptions(data_dir),
    )
