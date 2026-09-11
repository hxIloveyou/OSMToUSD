"""Unique full-building sheets, signage, and window/door details for the inbox.

These are meant to be applied as one sheet or a decal, not tiled like a 2-window
ambientCG facade. Not wired into USD generation.
"""
# 中文说明：inbox 整楼贴图/招牌/门窗细节（非整砖平铺；未接入 USD）。

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cityusd.inbox_assets import (
    OGA_PACK_PAGE,
    OGA_PACK_URL,
    OGA_ZIP_NAME,
    _http_download_file,
    _png_bytes_to_jpg,
    dest_path,
    oga_low_rise_role,
)

URBAN_JUNGLE_URL = "https://opengameart.org/sites/default/files/UrbanJungle_0.zip"
URBAN_JUNGLE_PAGE = "https://opengameart.org/content/urban-jungle"
URBAN_JUNGLE_ZIP = "oga_UrbanJungle.zip"

WIKI_UA = "CityUsd/1.0 (CC facade inbox; https://github.com/)"
WIKI_QUERIES = [
    "apartment building facade balcony",
    "shop front building street windows",
    "vertical shop sign",
    "Hong Kong neon vertical sign",
    "Japanese shop facade",
    "Taichung vertical signs",
    "building facade with billboard",
    "European shopfront windows",
    "tiled apartment balcony facade",
]


def oga_unique_sheet_role(filename: str) -> str | None:
    """Keep leftover OGA city photos as unique full-building sheets."""
    if oga_low_rise_role(filename) is not None:
        return None
    name = Path(filename).name.lower()
    if any(x in name for x in ("church", "empty", "construction", "portacabin", "corrugated")):
        return None
    if "office" in name:
        return "office"
    if any(x in name for x in ("factory", "warehouse")):
        return "industrial"
    if name.startswith("building_") or "derelict" in name:
        return "full"
    return None


def wiki_license_ok(short_name: str) -> tuple[bool, str]:
    lic = (short_name or "").lower()
    if "cc0" in lic or "public domain" in lic or lic in ("pd", "pd-self", "pd-us"):
        return True, "CC0"
    if lic.startswith("cc by") and "sa" not in lic:
        return True, short_name.strip() or "CC-BY"
    return False, short_name


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _asset(
    asset_id: str,
    *,
    bucket: str,
    role: str,
    part: str,
    source: str,
    page: str,
    notes: str,
    uv_mode: str,
    band: str | None = "low",
    license_id: str = "CC0-1.0",
    attribution: str | None = None,
) -> dict:
    return {
        "id": asset_id,
        "stem": asset_id,
        "source": source,
        "license": license_id if license_id.startswith("CC0") else license_id,
        "bucket": bucket,
        "part": part,
        "role": role,
        "suggested_band": band,
        "notes": notes,
        "status": "candidate",
        "page": page,
        "uv_mode": uv_mode,
        "attribution": attribution,
        "download": None,
        "zip_name": None,
    }


def ensure_oga_unique_sheets(library_dir: Path) -> list[dict]:
    import zipfile

    zip_path = Path(library_dir) / "_downloads" / OGA_ZIP_NAME
    if not zip_path.is_file():
        return []
    out: list[dict] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".png"):
                continue
            role = oga_unique_sheet_role(name)
            if role is None:
                continue
            stem = Path(name).stem.replace("-", "_")
            asset = _asset(
                f"oga_sheet_{stem}",
                bucket="sheets",
                role=role,
                part="facade",
                source="OpenGameArt",
                page=OGA_PACK_PAGE,
                notes="unique full-building sheet (do not tile)",
                uv_mode="unique_sheet",
                band="mid" if role == "office" else "low",
            )
            dest = dest_path(library_dir, asset)
            if not (dest.is_file() and dest.stat().st_size > 1000):
                _png_bytes_to_jpg(zf.read(name), dest)
                print(f"inbox: {asset['id']}", flush=True)
            out.append(asset)
    return out


def ensure_urban_jungle(library_dir: Path, timeout_s: float = 300.0) -> list[dict]:
    import zipfile

    from PIL import Image

    library_dir = Path(library_dir)
    zip_path = library_dir / "_downloads" / URBAN_JUNGLE_ZIP
    if not (zip_path.is_file() and zip_path.stat().st_size > 1_000_000):
        print("inbox: downloading Urban Jungle pack ...", flush=True)
        _http_download_file(URBAN_JUNGLE_URL, zip_path, timeout_s)
    out: list[dict] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            path = name.replace("\\", "/")
            lower = path.lower()
            if not lower.endswith(".jpg"):
                continue
            if "/building faces/" in lower:
                bucket, role, part, uv_mode, notes = (
                    "sheets",
                    "full",
                    "facade",
                    "unique_sheet",
                    "Urban Jungle unique building face",
                )
            elif "/signs/" in lower:
                bucket, role, part, uv_mode, notes = (
                    "signage",
                    "horizontal",
                    "decal",
                    "decal",
                    "Urban Jungle sign / billboard",
                )
            elif "/windows/" in lower:
                bucket, role, part, uv_mode, notes = (
                    "details",
                    "window",
                    "decal",
                    "decal",
                    "Urban Jungle window",
                )
            elif "/doors/" in lower:
                bucket, role, part, uv_mode, notes = (
                    "details",
                    "door",
                    "decal",
                    "decal",
                    "Urban Jungle door",
                )
            else:
                continue
            stem = Path(name).stem.replace("-", "_")
            asset = _asset(
                f"jungle_{stem}",
                bucket=bucket,
                role=role,
                part=part,
                source="OpenGameArt",
                page=URBAN_JUNGLE_PAGE,
                notes=notes,
                uv_mode=uv_mode,
            )
            dest = dest_path(library_dir, asset)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not (dest.is_file() and dest.stat().st_size > 1000):
                dest.write_bytes(zf.read(name))
                print(f"inbox: {asset['id']}", flush=True)
            if bucket == "signage" and dest.is_file():
                with Image.open(dest) as image:
                    width, height = image.size
                if height >= width * 1.35:
                    asset["role"] = "vertical"
                    asset["notes"] = "Urban Jungle vertical sign / billboard"
                    new_dest = dest_path(library_dir, asset)
                    if new_dest != dest:
                        new_dest.parent.mkdir(parents=True, exist_ok=True)
                        if not new_dest.exists():
                            dest.replace(new_dest)
                        elif dest.exists() and dest != new_dest:
                            dest.unlink()
            out.append(asset)
    return out


def _wiki_search(query: str, limit: int = 16) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "2048",
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urlencode(params)
    req = Request(url, headers={"User-Agent": WIKI_UA})
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    pages = (data.get("query") or {}).get("pages") or {}
    return list(pages.values())


def ensure_wiki_photos(library_dir: Path, timeout_s: float = 90.0, max_keep: int = 48) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for query in WIKI_QUERIES:
        if len(out) >= max_keep:
            break
        try:
            pages = _wiki_search(query)
        except Exception as exc:
            print(f"warning: wiki search skipped {query}: {exc}", flush=True)
            continue
        for page in pages:
            if len(out) >= max_keep:
                break
            title = page.get("title") or ""
            if title in seen:
                continue
            if "VIEW SOUTHEAST" in title.upper() or "HABS" in title.upper():
                continue
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            meta = info.get("extmetadata") or {}
            short = (meta.get("LicenseShortName", {}) or {}).get("value") or ""
            ok, lic = wiki_license_ok(short)
            if not ok:
                continue
            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)
            if width < 600 or height < 600:
                continue
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            seen.add(title)
            file_token = re.sub(r"[^a-zA-Z0-9]+", "_", title.replace("File:", ""))[:60].strip("_")
            portrait = height >= width * 1.25
            if "sign" in query or portrait:
                bucket, role, part, uv_mode = "signage", "vertical" if portrait else "horizontal", "decal", "decal"
                notes = "Wikimedia unique sign / billboard"
            else:
                bucket, role, part, uv_mode = "sheets", "full", "facade", "unique_sheet"
                notes = "Wikimedia unique building sheet (do not tile)"
            artist = _strip_html((meta.get("Artist", {}) or {}).get("value") or "")
            license_id = "CC0-1.0" if lic == "CC0" else lic
            asset = _asset(
                f"wiki_{file_token}",
                bucket=bucket,
                role=role,
                part=part,
                source="Wikimedia Commons",
                page="https://commons.wikimedia.org/wiki/" + title.replace(" ", "_"),
                notes=notes,
                uv_mode=uv_mode,
                license_id=license_id,
                attribution=artist or None,
            )
            dest = dest_path(library_dir, asset)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not (dest.is_file() and dest.stat().st_size > 1000):
                try:
                    _http_download_file(url, dest, timeout_s)
                    print(f"inbox: {asset['id']}", flush=True)
                    time.sleep(0.8)
                except Exception as exc:
                    msg = str(exc)
                    print(f"warning: wiki skipped {asset['id']}: {exc}", flush=True)
                    if "429" in msg:
                        print("warning: wiki rate limited, stopping Commons download", flush=True)
                        return out
                    continue
            out.append(asset)
    return out


def ensure_unique_packs(library_dir: Path) -> list[dict]:
    library_dir = Path(library_dir)
    rows: list[dict] = []
    rows.extend(ensure_oga_unique_sheets(library_dir))
    rows.extend(ensure_urban_jungle(library_dir))
    rows.extend(ensure_wiki_photos(library_dir))
    return rows
