"""CityEngine-style procedural albedo maps when AssetLibrary images are absent."""
# 中文说明：无库贴图时生成程序化 albedo。

from __future__ import annotations

import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

SIZE = 512


def write_photo_facade_png(
    path: Path,
    source: Path,
    hue_shift: int = 0,
    contrast: float = 1.12,
    size: int = 512,
    crop: int = 0,
    flip_x: bool = False,
    window_floors: int = 0,
    keep_sheet: bool = False,
) -> Path:
    """Resize a facade albedo. Unique sheets skip crop/window overlay so the whole face stays intact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(source).convert("RGB")
    img = ImageOps.exif_transpose(img)
    if keep_sheet:
        size = max(int(size), 1024)
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(float(contrast))
        img.save(path, quality=90)
        return path
    if int(crop) > 0:
        w, h = img.size
        if crop == 1:
            img = img.crop((0, 0, max(8, int(w * 0.75)), h))
        elif crop == 2:
            img = img.crop((min(w - 8, int(w * 0.25)), 0, w, h))
        else:
            img = img.crop(
                (int(w * 0.08), int(h * 0.04), max(int(w * 0.08) + 8, int(w * 0.92)), max(int(h * 0.04) + 8, int(h * 0.88)))
            )
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    if flip_x:
        img = ImageOps.mirror(img)
    if abs(int(hue_shift)) > 0:
        hsv = img.convert("HSV")
        h, s, v = hsv.split()
        h = h.point(lambda p: (p + int(hue_shift)) % 256)
        img = Image.merge("HSV", (h, s, v)).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(float(contrast))
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    if int(window_floors) > 0:
        img = _overlay_window_grid(img, int(window_floors))
    img.save(path)
    return path


def write_photo_roof_png(path: Path, source: Path, size: int = 512, contrast: float = 1.08) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(source).convert("RGB")
    img = ImageOps.exif_transpose(img)
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(float(contrast))
    img.save(path)
    return path


def _overlay_window_grid(img: Image.Image, floors: int) -> Image.Image:
    floors = max(3, int(floors))
    bays = 6 if floors <= 6 else 8
    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    cell_w, cell_h = max(8, w // bays), max(8, h // floors)
    for fy in range(floors):
        for bx in range(bays):
            x0 = bx * cell_w + cell_w // 5
            y0 = fy * cell_h + cell_h // 5
            draw.rectangle((x0, y0, x0 + cell_w // 2, y0 + cell_h // 2), fill=(22, 30, 42))
    return Image.blend(img, overlay, 0.26)


def write_solid_png(path: Path, rgb: tuple[int, int, int], size: int = SIZE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (size, size), rgb).save(path)
    return path


def _noise_fill(img: Image.Image, base: tuple[int, int, int], amp: int, seed: int) -> None:
    rng = random.Random(seed)
    px = img.load()
    w, h = img.size
    br, bg, bb = base
    for y in range(h):
        for x in range(w):
            d = rng.randint(-amp, amp)
            px[x, y] = (
                max(0, min(255, br + d)),
                max(0, min(255, bg + d)),
                max(0, min(255, bb + d)),
            )


def write_asphalt_png(path: Path, base: tuple[int, int, int], seed: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (SIZE, SIZE), base)
    _noise_fill(img, base, 12, seed)
    img.save(path)
    return path


def write_gravel_png(path: Path, base: tuple[int, int, int], seed: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (SIZE, SIZE), base)
    _noise_fill(img, base, 18, seed)
    rng = random.Random(seed + 7)
    draw = ImageDraw.Draw(img)
    for _ in range(900):
        x, y = rng.randint(0, SIZE - 1), rng.randint(0, SIZE - 1)
        c = rng.randint(80, 180)
        draw.ellipse((x, y, x + rng.randint(1, 4), y + rng.randint(1, 4)), fill=(c, c - 8, c - 16))
    img.save(path)
    return path


def _clamp_rgb(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return (
        max(0, min(255, int(rgb[0]))),
        max(0, min(255, int(rgb[1]))),
        max(0, min(255, int(rgb[2]))),
    )


def _shift(rgb: tuple[int, int, int], d: int) -> tuple[int, int, int]:
    return _clamp_rgb((rgb[0] + d, rgb[1] + d, rgb[2] + d))


def write_facade_png(
    path: Path,
    wall: tuple[int, int, int],
    window: tuple[int, int, int],
    floors: int,
    bays: int,
    seed: int,
    style: int = 0,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (SIZE, SIZE), wall)
    rng = random.Random(seed)
    draw = ImageDraw.Draw(img)
    floors = max(2, int(floors))
    bays = max(3, int(bays))
    style = int(style) % 8
    cell_w = SIZE // bays
    cell_h = SIZE // floors
    cornice = _shift(wall, -28)
    draw.rectangle((0, 0, SIZE, 10), fill=cornice)
    draw.rectangle((0, SIZE - 14, SIZE, SIZE), fill=_shift(wall, -18))
    if style == 0:
        _draw_punched_windows(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    elif style == 1:
        _draw_ribbon_windows(draw, rng, wall, window, floors, cell_h)
    elif style == 2:
        _draw_curtain_wall(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    elif style == 3:
        _draw_shop_base(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    elif style == 4:
        _draw_brick_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    elif style == 5:
        _draw_balcony_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    elif style == 6:
        _draw_fin_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    else:
        _draw_mixed_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    img.save(path)
    return path


def _win_color(rng: random.Random, window: tuple[int, int, int], lit_p: float = 0.18):
    if rng.random() < lit_p:
        return _clamp_rgb((window[0] + 70, window[1] + 55, window[2] + 20))
    return window


def _draw_punched_windows(draw, rng, wall, window, floors, bays, cell_w, cell_h):
    margin_x = max(4, cell_w // 5)
    margin_y = max(4, cell_h // 6)
    win_w = max(8, cell_w - 2 * margin_x)
    win_h = max(8, cell_h - 2 * margin_y)
    for fy in range(floors):
        for bx in range(bays):
            x0 = bx * cell_w + margin_x
            y0 = fy * cell_h + margin_y
            color = _win_color(rng, window)
            draw.rectangle((x0, y0, x0 + win_w, y0 + win_h), fill=color)
            draw.rectangle((x0, y0 + win_h - 3, x0 + win_w, y0 + win_h), fill=_shift(wall, -22))


def _draw_ribbon_windows(draw, rng, wall, window, floors, cell_h):
    for fy in range(floors):
        y0 = fy * cell_h + cell_h // 5
        y1 = y0 + max(10, cell_h // 2)
        draw.rectangle((8, y0, SIZE - 9, y1), fill=_win_color(rng, window, 0.12))
        for x in range(8, SIZE - 8, 28):
            draw.line((x, y0, x, y1), fill=_shift(wall, -30), width=2)


def _draw_curtain_wall(draw, rng, wall, window, floors, bays, cell_w, cell_h):
    mullion = _shift(wall, -40)
    for fy in range(floors):
        for bx in range(bays):
            x0, y0 = bx * cell_w, fy * cell_h
            draw.rectangle((x0 + 2, y0 + 2, x0 + cell_w - 3, y0 + cell_h - 3), fill=_win_color(rng, window, 0.22))
    for x in range(0, SIZE, cell_w):
        draw.line((x, 0, x, SIZE), fill=mullion, width=3)
    for y in range(0, SIZE, cell_h):
        draw.line((0, y, SIZE, y), fill=mullion, width=3)


def _draw_shop_base(draw, rng, wall, window, floors, bays, cell_w, cell_h):
    shop = _shift(wall, -35)
    draw.rectangle((0, SIZE - cell_h, SIZE, SIZE), fill=shop)
    for bx in range(bays):
        x0 = bx * cell_w + 6
        draw.rectangle((x0, SIZE - cell_h + 10, x0 + cell_w - 12, SIZE - 8), fill=_win_color(rng, window, 0.4))
    _draw_punched_windows(draw, rng, wall, window, max(1, floors - 1), bays, cell_w, cell_h)


def _draw_brick_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h):
    brick = _shift(wall, -12)
    for y in range(0, SIZE, 8):
        ox = 6 if (y // 8) % 2 else 0
        for x in range(-6, SIZE, 14):
            draw.rectangle((x + ox, y, x + ox + 12, y + 6), fill=_shift(brick, rng.randint(-8, 8)))
    margin_x = max(6, cell_w // 4)
    margin_y = max(6, cell_h // 5)
    for fy in range(floors):
        for bx in range(bays):
            x0 = bx * cell_w + margin_x
            y0 = fy * cell_h + margin_y
            draw.rectangle(
                (x0, y0, x0 + cell_w - 2 * margin_x, y0 + cell_h - 2 * margin_y),
                fill=_win_color(rng, window, 0.1),
            )


def _draw_balcony_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h):
    _draw_punched_windows(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    slab = _shift(wall, 24)
    rail = _shift(wall, -40)
    for fy in range(floors):
        y = fy * cell_h + cell_h - 8
        draw.rectangle((4, y, SIZE - 5, y + 6), fill=slab)
        draw.line((4, y - 6, SIZE - 5, y - 6), fill=rail, width=2)


def _draw_fin_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h):
    _draw_curtain_wall(draw, rng, wall, window, floors, bays, cell_w, cell_h)
    fin = _shift(wall, 18)
    for bx in range(bays):
        x = bx * cell_w + 3
        draw.rectangle((x, 0, x + 5, SIZE), fill=fin)


def _draw_mixed_facade(draw, rng, wall, window, floors, bays, cell_w, cell_h):
    for fy in range(floors):
        for bx in range(bays):
            if rng.random() < 0.28:
                continue
            x0 = bx * cell_w + cell_w // 5
            y0 = fy * cell_h + cell_h // 6
            draw.rectangle(
                (x0, y0, x0 + cell_w // 2, y0 + cell_h // 2),
                fill=_win_color(rng, window, 0.15),
            )


def write_roof_png(path: Path, base: tuple[int, int, int] = (110, 58, 42), style: int = 0) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (SIZE, SIZE), base)
    draw = ImageDraw.Draw(img)
    rng = random.Random(40 + int(style) + base[0])
    br, bg, bb = base
    style = int(style) % 8
    if style == 0:
        tile_h = 16
        for y in range(0, SIZE, tile_h):
            shade = 8 if (y // tile_h) % 2 == 0 else 0
            draw.rectangle((0, y, SIZE, y + tile_h - 2), fill=_clamp_rgb((br + shade, bg + shade, bb + shade)))
            for x in range(0, SIZE, 28):
                ox = 14 if (y // tile_h) % 2 else 0
                draw.line((x + ox, y, x + ox, y + tile_h), fill=_shift(base, -20), width=1)
    elif style == 1:
        for x in range(0, SIZE, 18):
            draw.rectangle((x, 0, x + 14, SIZE), fill=_shift(base, 6 if (x // 18) % 2 == 0 else -8))
            draw.line((x + 14, 0, x + 14, SIZE), fill=_shift(base, -28), width=2)
    elif style == 2:
        _noise_fill(img, base, 22, seed=80 + style)
        for _ in range(400):
            x, y = rng.randint(0, SIZE - 1), rng.randint(0, SIZE - 1)
            c = rng.randint(90, 170)
            draw.ellipse((x, y, x + rng.randint(2, 6), y + rng.randint(2, 6)), fill=(c, c - 6, c - 14))
    elif style == 3:
        img.paste(Image.new("RGB", (SIZE, SIZE), (62, 110, 58)))
        _noise_fill(img, (62, 110, 58), 16, seed=90)
        draw = ImageDraw.Draw(img)
        for y in range(40, SIZE, 64):
            draw.line((0, y, SIZE, y), fill=(48, 88, 46), width=2)
    elif style == 4:
        _noise_fill(img, base, 10, seed=100)
        draw = ImageDraw.Draw(img)
        for _ in range(7):
            x, y = rng.randint(20, SIZE - 80), rng.randint(20, SIZE - 80)
            draw.rectangle((x, y, x + 48, y + 32), fill=_shift(base, -30))
            draw.rectangle((x + 8, y + 6, x + 40, y + 14), fill=(70, 70, 74))
    elif style == 5:
        for y in range(0, SIZE, 32):
            for x in range(0, SIZE, 32):
                fill = base if (x // 32 + y // 32) % 2 == 0 else _shift(base, 18)
                draw.rectangle((x, y, x + 31, y + 31), fill=fill)
    elif style == 6:
        for y in range(0, SIZE, 36):
            draw.line((0, y, SIZE, y), fill=_shift(base, -24), width=2)
        for x in range(0, SIZE, 90):
            draw.line((x, 0, x, SIZE), fill=_shift(base, -18), width=1)
    else:
        for y in range(0, SIZE, 22):
            for x in range(0, SIZE, 22):
                ox = 11 if (y // 22) % 2 else 0
                draw.polygon(
                    [(x + ox + 11, y), (x + ox + 22, y + 11), (x + ox + 11, y + 22), (x + ox, y + 11)],
                    fill=_shift(base, rng.randint(-12, 12)),
                )
    img.save(path)
    return path


def write_water_png(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (SIZE, SIZE), (28, 92, 140))
    draw = ImageDraw.Draw(img)
    for i in range(14):
        y = 20 + i * 34
        draw.arc((-40, y, SIZE + 40, y + 28), 0, 180, fill=(48, 120, 168), width=2)
    img.save(path)
    return path


def write_grass_png(path: Path) -> Path:
    return write_asphalt_png(path, (62, 118, 48), seed=91)


def _cjk_font(size: int):
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for name in ("msyh.ttc", "msyhbd.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc", "msyh.ttc"):
        candidate = windir / "Fonts" / name
        if not candidate.is_file():
            continue
        try:
            return ImageFont.truetype(str(candidate), size)
        except Exception:
            continue
    return ImageFont.load_default()


def write_sign_board_png(path: Path, text: str = "道路", size: tuple[int, int] = (1024, 512)) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = int(size[0]), int(size[1])
    img = Image.new("RGB", (w, h), (18, 72, 168))
    draw = ImageDraw.Draw(img)
    draw.rectangle((8, 8, w - 9, h - 9), outline=(245, 245, 245), width=14)
    draw.rectangle((28, 70, w - 29, h - 70), fill=(245, 245, 245))
    label = (text or "").strip() or "道路"
    if len(label) > 14:
        label = label[:14]
    font_size = 120 if len(label) <= 4 else 88 if len(label) <= 8 else 64
    font = _cjk_font(font_size)
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (w - tw) / 2 - bbox[0]
    y = (h - th) / 2 - bbox[1]
    draw.text((x, y), label, font=font, fill=(16, 42, 110))
    img.save(path)
    return path


def write_arrow_decal_png(path: Path) -> Path:
    """White MUTCD/GB 5768 through-arrow on transparent background, tip to the right."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 512, 256
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    tip_x = w - 16
    head_x = int(w * 0.62)
    stem_top = int(h * 0.38)
    stem_bot = int(h * 0.62)
    head_half = int(h * 0.38)
    mid = h // 2
    draw.polygon(
        [
            (tip_x, mid),
            (head_x, mid - head_half),
            (head_x, stem_top),
            (20, stem_top),
            (20, stem_bot),
            (head_x, stem_bot),
            (head_x, mid + head_half),
        ],
        fill=white,
    )
    img.save(path)
    return path


def write_metal_png(path: Path) -> Path:
    return write_asphalt_png(path, (48, 48, 52), seed=3)


def write_lamp_head_png(path: Path) -> Path:
    return write_solid_png(path, (255, 214, 64), size=SIZE)


def write_bark_png(path: Path) -> Path:
    return write_asphalt_png(path, (92, 58, 32), seed=11)


def write_foliage_png(path: Path) -> Path:
    return write_asphalt_png(path, (36, 122, 42), seed=22)


def write_taipei_roof_pngs(buildings_dir: Path) -> dict[str, Path]:
    """Dark gray Taipei roofs: PU/asphalt membrane, concrete slab, corrugated sheet."""
    from cityusd.looks import ROOF_VARIANT_COUNT

    bld = Path(buildings_dir)
    bld.mkdir(parents=True, exist_ok=True)
    colors = [
        (58, 60, 62),
        (66, 68, 70),
        (52, 54, 56),
        (72, 74, 76),
        (48, 50, 54),
        (62, 64, 63),
        (54, 56, 58),
        (70, 71, 72),
        (44, 46, 48),
        (64, 66, 68),
        (50, 52, 55),
        (68, 69, 70),
    ]
    # membrane = 防水层, tile = 深灰水泥砖, metal = 浪板, panel = 分仓缝
    kinds = (
        "membrane",
        "tile",
        "metal",
        "panel",
        "membrane",
        "tile",
        "metal",
        "panel",
        "membrane",
        "tile",
        "metal",
        "panel",
    )
    out: dict[str, Path] = {}
    for i in range(ROOF_VARIANT_COUNT):
        key = f"roof_{i}"
        dest = bld / f"{key}.png"
        color = colors[i % len(colors)]
        kind = kinds[i % len(kinds)]
        if kind == "membrane":
            out[key] = write_asphalt_png(dest, color, seed=40 + i)
        elif kind == "metal":
            out[key] = write_roof_png(dest, color, style=1)
        elif kind == "panel":
            out[key] = write_roof_png(dest, color, style=6)
        else:
            out[key] = write_roof_png(dest, color, style=0)
    out["roof"] = out["roof_0"]
    return out


def ensure_scene_textures(
    textures_dir: Path,
    facade_photos: dict[str, list[Path]] | None = None,
    roof_photos: list[Path] | None = None,
    facade_uv_modes: dict[str, list[str]] | None = None,
    library_dir: Path | None = None,
) -> dict[str, Path]:
    """Write albedo PNGs into textures/{roads,buildings,water,vegetation,furniture}/.

    Inbox roof photos are ignored (too colorful). Roofs stay Taipei dark-gray procedural.
    When library_dir has materials/roads, prefer those albedos over procedural fills.
    """
    _ = roof_photos
    from cityusd.looks import facade_variant_count
    from cityusd.road_assets import ARROW_KIND_ORDER, install_road_library_textures

    root = Path(textures_dir)
    roads = root / "roads"
    bld = root / "buildings"
    water = root / "water"
    veg = root / "vegetation"
    furn = root / "furniture"
    out: dict[str, Path] = {}
    uv_modes: dict[str, str] = {}
    lib_tex = install_road_library_textures(root, library_dir)

    def _road(key: str, writer) -> None:
        if key in lib_tex:
            out[key] = lib_tex[key]
        else:
            out[key] = writer()

    _road("highway", lambda: write_asphalt_png(roads / "highway.png", (28, 28, 32), 1))
    _road("expressway", lambda: write_asphalt_png(roads / "expressway.png", (36, 36, 40), 2))
    _road("national", lambda: write_asphalt_png(roads / "national.png", (42, 42, 46), 3))
    _road("provincial", lambda: write_asphalt_png(roads / "provincial.png", (50, 50, 50), 4))
    _road("county", lambda: write_asphalt_png(roads / "county.png", (56, 56, 52), 5))
    _road("asphalt", lambda: write_asphalt_png(roads / "asphalt.png", (64, 64, 64), 6))
    _road("cement", lambda: write_asphalt_png(roads / "cement.png", (128, 128, 118), 7))
    _road("dirt", lambda: write_gravel_png(roads / "dirt.png", (118, 82, 42), 8))
    _road("path", lambda: write_gravel_png(roads / "path.png", (148, 124, 78), 9))
    _road("pavement", lambda: write_asphalt_png(roads / "pavement.png", (150, 144, 132), 10))
    _road("gravel", lambda: write_gravel_png(roads / "gravel.png", (110, 104, 96), 11))
    out["facade_low"] = write_facade_png(
        bld / "facade_low.png", (168, 122, 82), (40, 52, 70), floors=3, bays=5, seed=20
    )
    out["facade_mid"] = write_facade_png(
        bld / "facade_mid.png", (196, 188, 176), (50, 62, 82), floors=6, bays=6, seed=21
    )
    out["facade_high"] = write_facade_png(
        bld / "facade_high.png", (150, 164, 180), (36, 48, 68), floors=10, bays=7, seed=22
    )
    out["facade_tower"] = write_facade_png(
        bld / "facade_tower.png", (130, 150, 172), (28, 40, 58), floors=14, bays=8, seed=23
    )
    facade_walls = [
        (168, 122, 82),
        (196, 188, 176),
        (150, 80, 70),
        (88, 98, 108),
        (210, 200, 185),
        (120, 90, 70),
        (176, 154, 128),
        (96, 118, 102),
    ]
    facade_windows = [
        (40, 52, 70),
        (50, 62, 82),
        (36, 40, 48),
        (30, 44, 64),
        (70, 78, 88),
        (42, 38, 32),
        (48, 56, 72),
        (34, 50, 42),
    ]
    band_floors = {"low": 3, "mid": 8, "high": 10, "tower": 14}
    band_bays = {"low": 4, "mid": 4, "high": 6, "tower": 8}
    masonry_styles = (0, 3, 4, 5, 7, 0, 4, 3)
    photos = facade_photos or {}
    mode_lists = facade_uv_modes or {}
    for band, floors in band_floors.items():
        sources = list(photos.get(band) or [])
        modes = list(mode_lists.get(band) or [])
        n_var = facade_variant_count(band)
        for i in range(n_var):
            key = f"facade_{band}_{i}"
            dest = bld / f"{key}.png"
            if sources:
                src = sources[i % len(sources)]
                mode = modes[i % len(modes)] if modes else "tile"
                if len(modes) <= i and src:
                    from cityusd.inbox_bind import uv_mode_for_path

                    mode = uv_mode_for_path(src)
                reuse = i >= len(sources)
                sheet = mode == "unique_sheet" and not reuse
                out[key] = write_photo_facade_png(
                    dest,
                    src,
                    hue_shift=0,
                    contrast=1.05 + (i % 4) * 0.03,
                    crop=(0 if sheet or not reuse else (i % 3) + 1),
                    flip_x=reuse and (i % 2 == 0),
                    window_floors=0,
                    keep_sheet=sheet,
                    size=1024 if sheet else 512,
                )
                uv_modes[key] = "unique_sheet" if sheet else "tile"
            else:
                out[key] = write_facade_png(
                    dest,
                    facade_walls[i % len(facade_walls)],
                    facade_windows[i % len(facade_windows)],
                    floors=floors,
                    bays=band_bays[band] + (i % 2),
                    seed=30 + i + floors,
                    style=masonry_styles[i % len(masonry_styles)],
                )
                uv_modes[key] = "tile"
        if f"facade_{band}_0" in out:
            out[f"facade_{band}"] = out[f"facade_{band}_0"]
    out.update(write_taipei_roof_pngs(bld))
    out["arrow_fill"] = write_solid_png(furn / "arrow_fill.png", (255, 230, 70))
    out["arrow_decal"] = write_arrow_decal_png(furn / "arrow_decal.png")
    for kind in ARROW_KIND_ORDER:
        key = f"arrow_{kind}"
        if key in lib_tex:
            out[key] = lib_tex[key]
        elif kind == "straight":
            out[key] = out["arrow_decal"]
        else:
            # Missing specialty arrow → reuse straight procedural/library straight
            out[key] = out.get("arrow_straight", out["arrow_decal"])
    out["water"] = write_water_png(water / "water.png")
    out["grass"] = write_grass_png(veg / "grass.png")
    out["sign_board"] = write_sign_board_png(furn / "sign_board.png")
    out["metal"] = write_metal_png(furn / "metal.png")
    out["lamp_head"] = write_lamp_head_png(furn / "lamp_head.png")
    out["bark"] = write_bark_png(furn / "bark.png")
    out["foliage"] = write_foliage_png(furn / "foliage.png")
    out["_facade_uv"] = uv_modes  # type: ignore[assignment]
    lib_hits = sorted(k for k in lib_tex if k in out)
    if lib_hits:
        print(f"road textures from AssetLibrary: {len(lib_hits)} keys", flush=True)
    return out


def texture_rel_from_layers(key: str, written: dict[str, Path], textures_root: Path) -> str:
    path = written[key]
    rel = path.relative_to(textures_root).as_posix()
    return f"../textures/{rel}"
