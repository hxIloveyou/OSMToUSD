"""Slope occupancy from MAVS-centered elevation BMP (NATURE / Nav2).

Height decode (matches elevation_to_bmp):
  h_m = scale * (gray - 128)
"""

from __future__ import annotations

import numpy as np


def build_slope_occupancy(
    gray: np.ndarray,
    resolution: float,
    scale: float,
    max_slope: float,
) -> np.ndarray:
    """Return uint8 PGM grid: 254 free, 0 occupied (no unknown)."""
    if gray.ndim != 2:
        raise ValueError(f"expected 2D gray image, got shape {gray.shape}")
    h, w = gray.shape
    res = float(resolution)
    thr = float(max_slope)
    sc = float(scale)
    out = np.full((h, w), 254, dtype=np.uint8)

    def height_at(c: int, r: int) -> float | None:
        g = int(gray[r, c])
        if g <= 0:
            return None
        return sc * (g - 128.0)

    for r in range(h):
        for c in range(w):
            h0 = height_at(c, r)
            if h0 is None:
                out[r, c] = 0
                continue

            if c + 1 < w and c - 1 >= 0:
                hp = height_at(c + 1, r)
                hm = height_at(c - 1, r)
                dzdx = 0.0 if hp is None or hm is None else (hp - hm) / (2.0 * res)
            elif c + 1 < w:
                hp = height_at(c + 1, r)
                dzdx = 0.0 if hp is None else (hp - h0) / res
            elif c - 1 >= 0:
                hm = height_at(c - 1, r)
                dzdx = 0.0 if h0 is None or hm is None else (h0 - hm) / res
            else:
                dzdx = 0.0

            if r + 1 < h and r - 1 >= 0:
                hp = height_at(c, r + 1)
                hm = height_at(c, r - 1)
                dzdy = 0.0 if hp is None or hm is None else (hp - hm) / (2.0 * res)
            elif r + 1 < h:
                hp = height_at(c, r + 1)
                dzdy = 0.0 if hp is None else (hp - h0) / res
            elif r - 1 >= 0:
                hm = height_at(c, r - 1)
                dzdy = 0.0 if h0 is None or hm is None else (h0 - hm) / res
            else:
                dzdy = 0.0

            if (dzdx * dzdx + dzdy * dzdy) ** 0.5 > thr:
                out[r, c] = 0
    return out
