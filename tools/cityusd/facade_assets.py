"""Download CC0 building facades and roofs (ambientCG) and cache Color maps."""
# 中文说明：下载 ambientCG CC0 立面/屋顶并缓存 Color 贴图。

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

FACADE_FILES = [
    "Facade001_1K-JPG.zip",
    "Facade002_1K-JPG.zip",
    "Facade003_1K-JPG.zip",
    "Facade005_1K-JPG.zip",
    "Facade006_1K-JPG.zip",
    "Facade007_1K-JPG.zip",
    "Facade008_1K-JPG.zip",
    "Facade009_1K-JPG.zip",
    "Facade010_1K-JPG.zip",
    "Facade011_1K-JPG.zip",
    "Facade012_1K-JPG.zip",
    "Facade013_1K-JPG.zip",
    "Facade014_1K-JPG.zip",
    "Facade017_1K-JPG.zip",
    "Facade018A_1K-JPG.zip",
    "Facade018B_1K-JPG.zip",
    "Facade020A_1K-JPG.zip",
]

ROOF_FILES = [
    "RoofingTiles001_1K-JPG.zip",
    "RoofingTiles002_1K-JPG.zip",
    "RoofingTiles003_1K-JPG.zip",
    "RoofingTiles007_1K-JPG.zip",
    "RoofingTiles014_1K-JPG.zip",
    "RoofingCopper001_1K-JPG.zip",
    "Metal008_1K-JPG.zip",
    "Tiles074_1K-JPG.zip",
]

BAND_SOURCES = {
    "low": ("Facade002", "Facade005", "Facade006", "Facade009", "Facade003"),
    "mid": ("Facade008", "Facade007", "Facade011", "Facade017"),
    "high": ("Facade014", "Facade013", "Facade012", "Facade010"),
    "tower": ("Facade001", "Facade018A", "Facade018B", "Facade020A"),
}

_README = """CC0 building facades and roofs from ambientCG (https://ambientcg.com/).
License: Creative Commons CC0 1.0. No attribution required.
Used as albedo sources for CityUsd building materials.
"""


def ensure_facade_photos(cache_dir: Path, timeout_s: float = 60.0) -> list[Path]:
    """Return cached Color.jpg paths, downloading 1K zips when missing."""
    return _ensure_photos(cache_dir, FACADE_FILES, timeout_s, kind="facade")


def ensure_roof_photos(cache_dir: Path, timeout_s: float = 60.0) -> list[Path]:
    return _ensure_photos(cache_dir, ROOF_FILES, timeout_s, kind="roof")


def photos_by_band(photos: list[Path]) -> dict[str, list[Path]]:
    by_stem = {p.parent.name: p for p in photos}
    out: dict[str, list[Path]] = {}
    for band, stems in BAND_SOURCES.items():
        found = [by_stem[s] for s in stems if s in by_stem]
        out[band] = found
    return out


def _ensure_photos(cache_dir: Path, files: list[str], timeout_s: float, kind: str) -> list[Path]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    readme = cache_dir / "README.txt"
    if not readme.exists():
        readme.write_text(_README, encoding="utf-8")
    photos: list[Path] = []
    for filename in files:
        stem = filename.split("_")[0]
        dest = cache_dir / stem / "Color.jpg"
        if dest.is_file() and dest.stat().st_size > 1000:
            photos.append(dest)
            continue
        url = f"https://ambientcg.com/get?file={filename}"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            req = Request(url, headers={"User-Agent": "CityUsd/1.0 (CC0 material cache)"})
            with urlopen(req, timeout=timeout_s) as resp:
                payload = resp.read()
            _extract_color(payload, dest)
            if dest.is_file() and dest.stat().st_size > 1000:
                photos.append(dest)
                print(f"{kind} cache: {stem}", flush=True)
        except Exception as exc:
            print(f"warning: {kind} download skipped {stem}: {exc}", flush=True)
    return photos


def _extract_color(zip_bytes: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        color = None
        for name in names:
            lower = name.replace("\\", "/").lower()
            if lower.endswith("/") or "normal" in lower or "rough" in lower:
                continue
            if "color" in lower or "diff" in lower or "albedo" in lower:
                color = name
                break
        if color is None:
            jpgs = [n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png"))]
            if not jpgs:
                raise FileNotFoundError("no color map in zip")
            color = jpgs[0]
        dest.write_bytes(zf.read(color))
