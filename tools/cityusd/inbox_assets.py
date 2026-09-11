"""CC0 facade/roof candidates for AssetLibrary inbox. Does not change USD generation."""
# 中文说明：AssetLibrary inbox 候选材质下载与清单（不改 USD 生成）。

from __future__ import annotations

import io
import json
import os
import shutil
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

from cityusd.facade_assets import _extract_color

USER_AGENT = "CityUsd/1.0 (CC0 material inbox)"
INBOX_REL = Path("materials") / "buildings" / "inbox"

OGA_PACK_URL = (
    "https://opengameart.org/sites/default/files/buildings-apartments-shopfronts-shutters.zip"
)
OGA_PACK_PAGE = (
    "https://opengameart.org/content/free-urban-textures-buildings-apartments-shop-fronts"
)
OGA_ZIP_NAME = "oga_buildings-apartments-shopfronts-shutters.zip"


def oga_low_rise_role(filename: str) -> Optional[str]:
    """Map OGA pack filenames to shop / residential; skip offices, churches, industrial."""
    n = Path(filename).name.lower()
    if any(x in n for x in ("church", "office", "factory", "warehouse", "construction", "empty", "corrugated", "derelict", "portacabin")):
        return None
    if "apartment" in n or "house" in n:
        return "residential"
    if "dock" in n:
        return None
    if "shutter" in n:
        return "shop"
    if any(x in n for x in ("shop", "restaurant", "showroom", "pub", "garage", "loading_bay")):
        return "shop"
    if any(
        x in n
        for x in (
            "building_front",
            "building_h_windows",
            "building_modern",
            "building_side",
            "building_center",
            "windows",
        )
    ):
        return "residential"
    return None


def _acg(stem: str, bucket: str, part: str, band: Optional[str], notes: str) -> dict:
    return {
        "id": f"acg_{stem}",
        "stem": stem,
        "source": "ambientCG",
        "license": "CC0-1.0",
        "bucket": bucket,
        "part": part,
        "role": None,
        "suggested_band": band,
        "notes": notes,
        "status": "candidate",
        "page": f"https://ambientcg.com/view?id={stem}",
        "download": f"https://ambientcg.com/get?file={stem}_1K-JPG.zip",
        "zip_name": f"{stem}_1K-JPG.zip",
    }


def _ph(
    stem: str,
    bucket: str,
    part: str,
    band: Optional[str],
    notes: str,
    role: Optional[str] = None,
    ph_map: str = "Diffuse",
    id_suffix: str = "",
    uv_mode: str = "tile",
) -> dict:
    aid = f"ph_{stem}" + (f"_{id_suffix}" if id_suffix else "")
    return {
        "id": aid,
        "stem": stem,
        "source": "Poly Haven",
        "license": "CC0-1.0",
        "bucket": bucket,
        "part": part,
        "role": role,
        "ph_map": ph_map,
        "suggested_band": band,
        "notes": notes,
        "status": "candidate",
        "page": f"https://polyhaven.com/a/{stem}",
        "uv_mode": uv_mode,
        "download": None,
        "zip_name": None,
    }


# East-Asia-leaning: ceramic/concrete tile cladding, corrugated 浪板, glass towers, bitumen.
# Generic backup: remaining windowed European facades, clay/slate roofs.
INBOX_ASSETS: list[dict] = [
    _acg("Facade001", "east_asia", "facade", "tower", "glass curtain wall"),
    _acg("Facade018A", "east_asia", "facade", "tower", "skyscraper glass"),
    _acg("Facade018B", "east_asia", "facade", "tower", "skyscraper glass"),
    _acg("Facade018C", "east_asia", "facade", "tower", "skyscraper glass"),
    _acg("Facade019A", "east_asia", "facade", "tower", "skyscraper"),
    _acg("Facade019B", "east_asia", "facade", "tower", "skyscraper"),
    _acg("Facade019C", "east_asia", "facade", "tower", "skyscraper"),
    _acg("Facade020A", "east_asia", "facade", "tower", "skyscraper"),
    _acg("Facade020B", "east_asia", "facade", "tower", "skyscraper"),
    _acg("Facade020C", "east_asia", "facade", "tower", "skyscraper"),
    _acg("PaintedPlaster006", "east_asia", "facade", "low", "painted plaster apartment"),
    _ph("concrete_tile_facade", "east_asia", "facade", "low", "concrete/ceramic facade tiles"),
    _ph("rectangular_facade_tiles", "east_asia", "facade", "low", "rectangular facade tiles"),
    _ph("rectangular_facade_tiles_02", "east_asia", "facade", "low", "rectangular facade tiles"),
    _ph("square_tiled_wall", "east_asia", "facade", "low", "square tiled wall"),
    _ph("rounded_square_tiled_wall", "east_asia", "facade", "mid", "rounded square tiled wall"),
    _ph("exterior_wall_cladding_03", "east_asia", "facade", "mid", "plaster cladding"),
    _ph("factory_wall", "east_asia", "facade", "mid", "corrugated factory wall"),
    _ph("container_side", "east_asia", "facade", "mid", "shipping-container corrugation"),
    _ph("asbestos_sheet", "east_asia", "facade", "low", "corrugated sheet (浪板 look)"),
    _ph("asbestos_sheet_02", "east_asia", "facade", "low", "corrugated sheet (浪板 look)"),
    _acg("RoofingTiles006", "east_asia", "roof", None, "modern roof tiles"),
    _acg("RoofingTiles009", "east_asia", "roof", None, "black modern roof tiles"),
    _acg("RoofingTiles010", "east_asia", "roof", None, "grey/white modern roof tiles"),
    _acg("RoofingTiles015B", "east_asia", "roof", None, "grey clay / metal-like"),
    _acg("CorrugatedSteel009", "east_asia", "roof", None, "corrugated steel 浪板"),
    _acg("Metal008", "east_asia", "roof", None, "sheet metal"),
    _ph("corrugated_iron", "east_asia", "roof", None, "corrugated iron 铁皮"),
    _ph("corrugated_iron_02", "east_asia", "roof", None, "corrugated iron 铁皮"),
    _ph("corrugated_iron_03", "east_asia", "roof", None, "corrugated iron 铁皮"),
    _ph("worn_corrugated_iron", "east_asia", "roof", None, "worn corrugated iron"),
    _ph("box_profile_metal_sheet", "east_asia", "roof", None, "box-profile 浪板"),
    _ph("bitumen", "east_asia", "roof", None, "flat bitumen roof"),
    _ph("ceramic_roof_01", "east_asia", "roof", None, "ceramic roof tiles"),
    _ph("grey_roof_tiles", "east_asia", "roof", None, "grey roof tiles"),
    _ph("grey_roof_tiles_02", "east_asia", "roof", None, "grey roof tiles"),
    _acg("Facade002", "generic", "facade", "low", "glazed facade"),
    _acg("Facade003", "generic", "facade", "low", "glazed facade"),
    _acg("Facade004", "generic", "facade", "low", "glazed facade"),
    _acg("Facade005", "generic", "facade", "low", "glazed facade"),
    _acg("Facade006", "generic", "facade", "mid", "glazed facade"),
    _acg("Facade007", "generic", "facade", "mid", "windowed facade"),
    _acg("Facade008", "generic", "facade", "mid", "windowed facade"),
    _acg("Facade009", "generic", "facade", "mid", "windowed night facade"),
    _acg("Facade010", "generic", "facade", "high", "windowed facade"),
    _acg("Facade011", "generic", "facade", "mid", "windowed facade"),
    _acg("Facade012", "generic", "facade", "high", "skyscraper windows"),
    _acg("Facade013", "generic", "facade", "high", "skyscraper windows"),
    _acg("Facade014", "generic", "facade", "high", "skyscraper windows"),
    _acg("Facade015", "generic", "facade", "high", "skyscraper windows"),
    _acg("Facade016", "generic", "facade", "high", "skyscraper windows"),
    _acg("Facade017", "generic", "facade", "mid", "skyscraper windows"),
    _ph("exterior_wall_cladding", "generic", "facade", "low", "brick cladding"),
    _ph("exterior_wall_cladding_02", "generic", "facade", "low", "brick cladding"),
    _acg("RoofingTiles001", "generic", "roof", None, "slate / old city"),
    _acg("RoofingTiles002", "generic", "roof", None, "round slate"),
    _acg("RoofingTiles003", "generic", "roof", None, "square slate"),
    _acg("RoofingTiles007", "generic", "roof", None, "brown modern tiles"),
    _acg("RoofingTiles008", "generic", "roof", None, "mossy tiles"),
    _acg("RoofingTiles011A", "generic", "roof", None, "clay tiles"),
    _acg("RoofingTiles012A", "generic", "roof", None, "clay tiles"),
    _acg("RoofingTiles013A", "generic", "roof", None, "clay tiles"),
    _acg("RoofingTiles014A", "generic", "roof", None, "clay tiles"),
    _acg("Tiles074", "generic", "roof", None, "tile mix"),
    _ph("clay_roof_tiles", "generic", "roof", None, "clay roof tiles"),
    _ph("clay_roof_tiles_02", "generic", "roof", None, "clay roof tiles"),
    _ph("clay_roof_tiles_03", "generic", "roof", None, "clay roof tiles"),
    _ph("roof_tiles", "generic", "roof", None, "roof tiles"),
    _ph("roof_tiles_14", "generic", "roof", None, "roof tiles"),
    # Low-rise 1–3F: ordinary windows, balconies, shopfronts, shutters (not curtain-wall).
    _ph("rusty_metal_shutter", "low_rise", "facade", "low", "shop roller shutter", role="shop"),
    _ph("rusted_shutter", "low_rise", "facade", "low", "shop shutter", role="shop"),
    _ph("worn_shutter", "low_rise", "facade", "low", "worn shop shutter", role="shop"),
    _ph("wood_shutter", "low_rise", "facade", "low", "wood shutter / window", role="shop"),
    _ph(
        "modular_urban_apartments_facade",
        "low_rise",
        "facade",
        "low",
        "urban apartment facade (windows/balconies)",
        role="residential",
        ph_map="Diffuse",
        id_suffix="diffuse",
    ),
    _ph(
        "modular_urban_apartments_facade",
        "low_rise",
        "facade",
        "low",
        "apartment windows/AC/objects atlas",
        role="residential",
        ph_map="objects_diff",
        id_suffix="objects",
    ),
    _ph(
        "modular_urban_apartments_facade",
        "low_rise",
        "facade",
        "low",
        "apartment plaster wall",
        role="residential",
        ph_map="plaster_diff",
        id_suffix="plaster",
    ),
    _ph(
        "modular_urban_apartments_facade",
        "low_rise",
        "facade",
        "low",
        "apartment window/balcony trim",
        role="residential",
        ph_map="trim_01_diff",
        id_suffix="trim01",
    ),
    _ph(
        "modular_urban_apartments_facade",
        "low_rise",
        "facade",
        "low",
        "apartment balcony/rail trim",
        role="residential",
        ph_map="trim_02_diff",
        id_suffix="trim02",
    ),
    _ph(
        "modular_factory_facade",
        "details",
        "facade",
        "mid",
        "factory windows module (multi-storey)",
        role="window",
        ph_map="windows_diff",
        id_suffix="windows",
    ),
    _ph(
        "modular_factory_facade",
        "details",
        "facade",
        "low",
        "factory doors / loading",
        role="door",
        ph_map="doors_diff",
        id_suffix="doors",
    ),
    _ph(
        "modular_factory_facade",
        "details",
        "facade",
        "low",
        "garage / loading bay",
        role="door",
        ph_map="garage_diff",
        id_suffix="garage",
    ),
    _ph(
        "modular_fire_escape",
        "details",
        "decal",
        "mid",
        "fire escape spanning floors",
        role="overlay",
        ph_map="01_diff",
        id_suffix="01",
        uv_mode="decal",
    ),
    _ph(
        "modular_fire_escape",
        "details",
        "decal",
        "mid",
        "fire escape variant spanning floors",
        role="overlay",
        ph_map="02_diff",
        id_suffix="02",
        uv_mode="decal",
    ),
    _ph(
        "rollershutter_door",
        "signage",
        "decal",
        "low",
        "full-height roller shutter",
        role="overlay",
        uv_mode="decal",
    ),
    _ph(
        "rollershutter_window_01",
        "details",
        "decal",
        "low",
        "window roller shutter",
        role="window",
        uv_mode="decal",
    ),
    _ph(
        "rollershutter_window_02",
        "details",
        "decal",
        "low",
        "window roller shutter",
        role="window",
        uv_mode="decal",
    ),
    _ph(
        "rollershutter_window_03",
        "details",
        "decal",
        "low",
        "window roller shutter",
        role="window",
        uv_mode="decal",
    ),
]

_README = """建筑立面 / 屋顶候选库（未接入 USD 生成）。

按用途分目录，资源管理器里直接预览。清单见 inbox_manifest.json（含 folder、uv_mode）。

  facades/tileable/highrise    可平铺·高层玻璃幕/窗格
  facades/tileable/midrise     可平铺·多层窗格
  facades/tileable/cladding    可平铺·瓷砖/抹灰/砖
  facades/tileable/metal       可平铺·铁皮/浪板墙
  facades/sheets/residential   整栋立面·住宅公寓（不要 UV 平铺）
  facades/sheets/shopfront     整栋立面·底商门面
  facades/sheets/office        整栋立面·办公
  facades/sheets/industrial    整栋立面·厂房仓库
  roofs/tile                   屋顶·瓦
  roofs/metal                  屋顶·铁皮/沥青
  signage/vertical             招牌·竖招（可跨多层）
  signage/horizontal           招牌·横招
  signage/overlay              招牌·整面卷帘等
  details/windows              零件·窗
  details/doors                零件·门
  details/shutters             零件·卷帘/窗板
  details/balconies            零件·阳台/窗套
  details/overlays             零件·消防梯等跨层构件

uv_mode: tile=可平铺；unique_sheet=一面墙一张图；decal=单独贴花。
许可见各条 license / attribution（多为 CC0，维基部分为 CC BY）。
"""


def inbox_root(library_dir: Path) -> Path:
    return Path(library_dir) / INBOX_REL


def layout_parts(asset: dict) -> tuple[str, ...]:
    """Browse folders for later picking. Independent of download-source buckets."""
    aid = str(asset.get("id") or "")
    notes = str(asset.get("notes") or "").lower()
    blob = f"{aid} {notes}".lower()
    bucket = asset.get("bucket")
    role = asset.get("role")
    part = asset.get("part")
    band = asset.get("suggested_band")

    if part == "roof":
        if any(w in blob for w in ("corrugat", "metal", "bitumen", "浪板", "iron", "steel", "copper")):
            return ("roofs", "metal")
        return ("roofs", "tile")

    if "shutter" in blob:
        if role == "overlay" and bucket == "signage":
            return ("signage", "overlay")
        return ("details", "shutters")

    if bucket == "signage" or role in ("vertical", "horizontal"):
        if role == "vertical":
            return ("signage", "vertical")
        if role == "overlay":
            return ("signage", "overlay")
        return ("signage", "horizontal")

    if any(w in blob for w in ("_trim", "_objects", "balcony", "窗套")):
        return ("details", "balconies")
    if "plaster" in aid.lower() and bucket == "low_rise":
        return ("facades", "tileable", "cladding")

    if bucket == "details" or part == "decal":
        if role == "window" or "window" in blob:
            return ("details", "windows")
        if role == "door" or "door" in blob or "garage" in blob:
            return ("details", "doors")
        return ("details", "overlays")

    if bucket == "low_rise":
        if role == "shop":
            return ("facades", "sheets", "shopfront")
        return ("facades", "sheets", "residential")

    if bucket == "sheets":
        if role == "office":
            return ("facades", "sheets", "office")
        if role == "industrial":
            return ("facades", "sheets", "industrial")
        return ("facades", "sheets", "residential")

    if any(w in blob for w in ("corrugat", "factory_wall", "container", "asbestos", "浪板")):
        return ("facades", "tileable", "metal")
    if any(w in blob for w in ("tile", "plaster", "cladding", "brick")):
        return ("facades", "tileable", "cladding")
    if band in ("tower", "high") or any(w in notes for w in ("skyscraper", "glass curtain", "glass")):
        return ("facades", "tileable", "highrise")
    return ("facades", "tileable", "midrise")


def layout_rel(asset: dict) -> str:
    parts = layout_parts(asset)
    return "/".join(parts)


def dest_path(library_dir: Path, asset: dict) -> Path:
    folder = Path(*layout_parts(asset))
    return inbox_root(library_dir) / folder / f"{asset['id']}_Color.jpg"


def relative_file(asset: dict) -> str:
    folder = Path(*layout_parts(asset))
    rel = INBOX_REL / folder / f"{asset['id']}_Color.jpg"
    return str(rel).replace("\\", "/")


def legacy_dest_path(library_dir: Path, asset: dict) -> Path:
    """Pre-reorganization path: inbox/<bucket>/<role or parts>/id_Color.jpg."""
    role = asset.get("role")
    folder = role if role else f"{asset.get('part') or 'facade'}s"
    return inbox_root(library_dir) / str(asset.get("bucket") or "") / str(folder) / f"{asset['id']}_Color.jpg"


def validate_catalog(assets: list[dict] | None = None) -> list[dict]:
    """Raise if ids collide or buckets/parts are invalid."""
    rows = list(assets if assets is not None else INBOX_ASSETS)
    seen: set[str] = set()
    for a in rows:
        if a["id"] in seen:
            raise ValueError(f"duplicate inbox id {a['id']}")
        seen.add(a["id"])
        if a["bucket"] not in (
            "east_asia",
            "generic",
            "low_rise",
            "sheets",
            "signage",
            "details",
        ):
            raise ValueError(f"bad bucket {a['id']}")
        if a["part"] not in ("facade", "roof", "decal"):
            raise ValueError(f"bad part {a['id']}")
        if a["part"] in ("facade", "decal") and a["suggested_band"] not in (
            "low",
            "mid",
            "high",
            "tower",
            None,
        ):
            raise ValueError(f"facade missing band {a['id']}")
        allowed_roles = {
            "east_asia": {None},
            "generic": {None},
            "low_rise": {"shop", "residential", "balcony"},
            "sheets": {"full", "office", "industrial"},
            "signage": {"vertical", "horizontal", "overlay"},
            "details": {"window", "door", "overlay"},
        }
        if a.get("role") not in allowed_roles[a["bucket"]]:
            raise ValueError(f"bad role {a['id']}")
        lic = str(a.get("license") or "")
        lic_u = lic.upper().replace("_", " ")
        if not (lic_u.startswith("CC0") or lic_u.startswith("CC BY") or lic_u.startswith("CC-BY")):
            raise ValueError(f"non-CC {a['id']}")
    return rows


def _http_get(url: str, timeout_s: float, retries: int = 4) -> bytes:
    last: Exception | None = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout_s) as resp:
                return resp.read()
        except Exception as exc:
            last = exc
            time.sleep(1.2 * (i + 1))
    raise last  # type: ignore[misc]


def _polyhaven_map_1k_jpg(stem: str, map_name: str, timeout_s: float) -> str:
    meta = json.loads(_http_get(f"https://api.polyhaven.com/files/{stem}", timeout_s).decode("utf-8"))
    node = meta.get(map_name) or meta.get("Diffuse") or meta.get("diff")
    if not isinstance(node, dict):
        raise KeyError(f"Poly Haven {stem}: no map {map_name}")
    k1 = node.get("1k") or node.get("2k")
    if not isinstance(k1, dict):
        raise KeyError(f"Poly Haven {stem}: no 1k/2k for {map_name}")
    jpg = k1.get("jpg") or k1.get("png")
    if not isinstance(jpg, dict) or not jpg.get("url"):
        raise KeyError(f"Poly Haven {stem}: no jpg url for {map_name}")
    return str(jpg["url"])


def download_asset(asset: dict, dest: Path, timeout_s: float = 90.0) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1000:
        return True
    try:
        if asset["source"] == "ambientCG":
            payload = _http_get(asset["download"], timeout_s)
            _extract_color(payload, dest)
        else:
            url = _polyhaven_map_1k_jpg(asset["stem"], asset.get("ph_map") or "Diffuse", timeout_s)
            dest.write_bytes(_http_get(url, timeout_s))
        ok = dest.is_file() and dest.stat().st_size > 1000
        if ok:
            print(f"inbox: {asset['id']}", flush=True)
        return ok
    except Exception as exc:
        print(f"warning: inbox skipped {asset['id']}: {exc}", flush=True)
        return False


def write_manifest(library_dir: Path, assets: list[dict]) -> Path:
    root = inbox_root(library_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.txt").write_text(_README, encoding="utf-8")
    entries = []
    for a in assets:
        rel = relative_file(a)
        on_disk = dest_path(library_dir, a)
        entries.append(
            {
                "id": a["id"],
                "file": rel,
                "present": on_disk.is_file() and on_disk.stat().st_size > 1000,
                "source": a["source"],
                "license": a["license"],
                "bucket": a["bucket"],
                "part": a["part"],
                "suggested_band": a["suggested_band"],
                "role": a.get("role"),
                "folder": layout_rel(a),
                "uv_mode": a.get("uv_mode") or "tile",
                "attribution": a.get("attribution"),
                "notes": a["notes"],
                "status": a["status"],
                "page": a["page"],
            }
        )
    payload = {
        "catalog_version": "1.0",
        "purpose": "candidate facades/roofs; not consumed by build_city_usd",
        "license": "CC0-1.0",
        "counts": {
            "listed": len(entries),
            "present": sum(1 for e in entries if e["present"]),
            "by_folder": dict(Counter(e["folder"] for e in entries)),
        },
        "assets": entries,
    }
    path = root / "inbox_manifest.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _http_download_file(url: str, dest: Path, timeout_s: float, retries: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 CityUsd/1.0 (CC0 material inbox)"})
            with urlopen(req, timeout=timeout_s) as resp, open(dest, "wb") as out:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            if dest.is_file() and dest.stat().st_size > 1000:
                return
        except Exception as exc:
            last = exc
            time.sleep(1.2 * (i + 1))
    raise last  # type: ignore[misc]


def _png_bytes_to_jpg(data: bytes, dest: Path) -> None:
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    bg = Image.new("RGB", image.size, (36, 36, 36))
    bg.paste(image, mask=image.split()[-1])
    bg.save(dest, "JPEG", quality=90, optimize=True)


def _oga_asset(stem: str, role: str) -> dict:
    return {
        "id": f"oga_{stem}",
        "stem": stem,
        "source": "OpenGameArt",
        "license": "CC0-1.0",
        "bucket": "low_rise",
        "part": "facade",
        "role": role,
        "suggested_band": "low",
        "notes": f"OGA urban pack ({role})",
        "status": "candidate",
        "page": OGA_PACK_PAGE,
        "download": OGA_PACK_URL,
        "zip_name": OGA_ZIP_NAME,
    }


def ensure_oga_low_rise(library_dir: Path, timeout_s: float = 300.0) -> list[dict]:
    """Extract shopfront / apartment / shutter albedos from the CC0 OGA city pack."""
    library_dir = Path(library_dir)
    zip_path = library_dir / "_downloads" / OGA_ZIP_NAME
    if not (zip_path.is_file() and zip_path.stat().st_size > 1_000_000):
        print("inbox: downloading OpenGameArt low-rise pack ...", flush=True)
        _http_download_file(OGA_PACK_URL, zip_path, timeout_s)
    extracted: list[dict] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith("/") or not name.lower().endswith(".png"):
                continue
            role = oga_low_rise_role(name)
            if role is None:
                continue
            stem = Path(name).stem.replace("-", "_")
            asset = _oga_asset(stem, role)
            dest = dest_path(library_dir, asset)
            if not (dest.is_file() and dest.stat().st_size > 1000):
                _png_bytes_to_jpg(zf.read(name), dest)
                print(f"inbox: {asset['id']}", flush=True)
            extracted.append(asset)
    return extracted


def ensure_inbox(library_dir: Path, timeout_s: float = 90.0) -> dict:
    assets = validate_catalog()
    ok = 0
    fail: list[str] = []
    for asset in assets:
        dest = dest_path(library_dir, asset)
        if download_asset(asset, dest, timeout_s=timeout_s):
            ok += 1
        else:
            fail.append(asset["id"])
    oga = ensure_oga_low_rise(library_dir)
    from cityusd.inbox_unique import ensure_unique_packs

    extra = ensure_unique_packs(library_dir)
    assets = validate_catalog(assets + oga + extra)
    extra_ok = sum(1 for a in oga + extra if dest_path(library_dir, a).is_file())
    ok += extra_ok
    rehome_inbox(library_dir, assets)
    manifest = write_manifest(library_dir, assets)
    return {"ok": ok, "fail": fail, "manifest": str(manifest), "listed": len(assets)}


def _find_existing_file(library_dir: Path, asset: dict, old_rel: str | None = None) -> Path | None:
    root = inbox_root(library_dir)
    candidates: list[Path] = []
    if old_rel:
        candidates.append(Path(library_dir) / old_rel)
    candidates.append(dest_path(library_dir, asset))
    candidates.append(legacy_dest_path(library_dir, asset))
    if root.is_dir():
        candidates.extend(root.rglob(f"{asset['id']}_Color.jpg"))
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file() and path.stat().st_size > 1000:
            return path
    return None


def _prune_empty_dirs(root: Path) -> None:
    if not root.is_dir():
        return
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        path = Path(dirpath)
        if path == root:
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            path.rmdir()


def rehome_inbox(library_dir: Path, assets: list[dict] | None = None) -> dict:
    """Move existing Color maps into browse folders. Does not download."""
    library_dir = Path(library_dir)
    root = inbox_root(library_dir)
    rows = list(assets) if assets is not None else []
    if not rows:
        manifest_path = root / "inbox_manifest.json"
        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows = list(payload.get("assets") or [])
    moved = 0
    missing: list[str] = []
    for asset in rows:
        old_rel = asset.get("file") if str(asset.get("file") or "").endswith(".jpg") else None
        src = _find_existing_file(library_dir, asset, old_rel)
        dest = dest_path(library_dir, asset)
        if src is None:
            missing.append(asset["id"])
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() == dest.resolve():
            continue
        if dest.exists() and dest.stat().st_size > 1000:
            if src.resolve() != dest.resolve():
                src.unlink()
            continue
        shutil.move(str(src), str(dest))
        moved += 1
        print(f"rehome: {asset['id']} -> {layout_rel(asset)}", flush=True)
    for leftover in ("east_asia", "generic", "low_rise", "sheets"):
        old = root / leftover
        if old.is_dir():
            _prune_empty_dirs(old)
            try:
                old.rmdir()
            except OSError:
                pass
    _prune_empty_dirs(root)
    return {"moved": moved, "missing": missing, "listed": len(rows), "assets": rows}
