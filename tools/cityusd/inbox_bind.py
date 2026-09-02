"""Bind AssetLibrary inbox facades/roofs into OSM building bands."""

from __future__ import annotations

from pathlib import Path

from cityusd.inbox_assets import INBOX_REL

from cityusd.inbox_assets import INBOX_REL

BAND_FOLDERS: dict[str, list[str]] = {
    "low": [
        "facades/sheets/shopfront",
        "facades/sheets/residential",
        "facades/tileable/cladding",
    ],
    "mid": [
        "facades/sheets/residential",
        "facades/tileable/cladding",
        "facades/tileable/midrise",
    ],
    "high": [
        "facades/sheets/office",
        "facades/tileable/midrise",
        "facades/tileable/highrise",
    ],
    "tower": [
        "facades/sheets/office",
        "facades/sheets/residential",
        "facades/tileable/highrise",
    ],
}

LOW_SHOP_FOLDERS = ["facades/sheets/shopfront"]
LOW_HOUSE_FOLDERS = ["facades/sheets/residential", "facades/tileable/cladding"]
ROOF_FOLDERS = ["roofs/tile", "roofs/metal"]

SHOP_BUILDING = {
    "retail",
    "commercial",
    "shop",
    "supermarket",
    "kiosk",
    "warehouse",
    "industrial",
    "hangar",
    "garages",
    "garage",
}
SHOP_AMENITY = {
    "restaurant",
    "cafe",
    "fast_food",
    "pharmacy",
    "bank",
    "bar",
    "pub",
    "marketplace",
    "fuel",
}


def is_shop_building(tags: dict | None) -> bool:
    tags = tags or {}
    kind = str(tags.get("building") or "").strip().lower()
    if kind in SHOP_BUILDING:
        return True
    if tags.get("shop"):
        return True
    amenity = str(tags.get("amenity") or "").strip().lower()
    return amenity in SHOP_AMENITY


def _jpgs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    files.sort(key=lambda p: p.name.lower())
    return files


def uv_mode_for_path(path: Path) -> str:
    text = str(path).replace("\\", "/")
    if "/facades/sheets/" in text:
        return "unique_sheet"
    # ambientCG highrise modules are a 10×10 window grid; tiling them looks like noise.
    if "/facades/tileable/highrise" in text:
        return "unique_sheet"
    return "tile"


def list_inbox_photos(library_dir: Path, rel_folders: list[str]) -> list[Path]:
    root = Path(library_dir) / INBOX_REL
    out: list[Path] = []
    seen: set[str] = set()
    for rel in rel_folders:
        for path in _jpgs(root / rel):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    return out


def inbox_facade_sources(library_dir: Path) -> dict[str, list[Path]]:
    library_dir = Path(library_dir)
    return {band: list_inbox_photos(library_dir, folders) for band, folders in BAND_FOLDERS.items()}


def inbox_low_pools(library_dir: Path) -> tuple[list[Path], list[Path]]:
    library_dir = Path(library_dir)
    shops = list_inbox_photos(library_dir, LOW_SHOP_FOLDERS)
    houses = list_inbox_photos(library_dir, LOW_HOUSE_FOLDERS)
    return shops, houses


def inbox_roof_sources(library_dir: Path) -> list[Path]:
    return list_inbox_photos(Path(library_dir), ROOF_FOLDERS)


def default_inbox_library() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "assets" / "AssetLibrary"


def resolve_asset_library_root(
    assets_dir: Path | None = None,
    data_dir: Path | None = None,
) -> Path | None:
    """Find AssetLibrary root containing materials/buildings/inbox."""
    candidates: list[Path] = []
    if assets_dir is not None:
        candidates.append(Path(assets_dir))
        candidates.append(Path(assets_dir) / "AssetLibrary")
    if data_dir is not None:
        base = Path(data_dir) / "assets"
        for p in (base, base / "AssetLibrary"):
            if p not in candidates:
                candidates.append(p)
    default = default_inbox_library()
    if default not in candidates:
        candidates.append(default)
    for root in candidates:
        if (root / INBOX_REL).is_dir():
            return root
    return None


def bind_inbox_photos(
    library_dir: Path | None = None,
) -> tuple[dict[str, list[Path]], list[Path], dict[str, list[str]]]:
    """Pick inbox photos per band. Empty photos if inbox is missing (procedural fallback)."""
    from cityusd.looks import LOW_SHOP_VARIANTS, facade_variant_count

    lib = Path(library_dir) if library_dir is not None else default_inbox_library()
    if not (lib / INBOX_REL).is_dir():
        return {}, [], {}

    shops, houses = inbox_low_pools(lib)
    by_band = inbox_facade_sources(lib)
    n_low = facade_variant_count("low")
    n_shop = min(LOW_SHOP_VARIANTS, n_low)
    low: list[Path] = []
    low_modes: list[str] = []
    if shops:
        for i in range(n_shop):
            path = shops[i % len(shops)]
            low.append(path)
            low_modes.append(uv_mode_for_path(path))
    house_slots = n_low - len(low)
    house_pool = houses or shops
    if house_pool and house_slots > 0:
        for i in range(house_slots):
            path = house_pool[i % len(house_pool)]
            low.append(path)
            low_modes.append(uv_mode_for_path(path))
    if low:
        by_band["low"] = low

    modes: dict[str, list[str]] = {}
    if low:
        modes["low"] = low_modes
    for band, paths in by_band.items():
        if band in modes or not paths:
            continue
        modes[band] = [uv_mode_for_path(p) for p in paths]

    photos = {band: paths for band, paths in by_band.items() if paths}
    roofs = inbox_roof_sources(lib)
    return photos, roofs, {band: modes[band] for band in photos if band in modes}
