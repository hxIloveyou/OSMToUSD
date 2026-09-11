# 中文说明：三角化与网格工具（earcut 等）。
from __future__ import annotations

from typing import List, Tuple

import mapbox_earcut as earcut
import numpy as np
from shapely.geometry.base import BaseGeometry

from cityusd.types import CM_PER_M

MIN_AREA_M2 = 0.05

Point2D = Tuple[float, float]
Point3D = Tuple[float, float, float]
Face = Tuple[int, int, int]


def triangulate_polygon(poly) -> Tuple[List[Point2D], List[Face]]:
    """Return 2D verts + triangle indices via mapbox_earcut. Empty if invalid."""
    if poly is None or poly.is_empty or not getattr(poly, "is_valid", False):
        return [], []

    area = getattr(poly, "area", 0.0)
    if area < MIN_AREA_M2:
        return [], []

    coords: List[Point2D] = []
    ring_counts: List[int] = []

    rings = [poly.exterior, *poly.interiors]
    for ring in rings:
        pts = list(ring.coords)[:-1]
        if len(pts) < 3:
            continue
        coords.extend((float(x), float(y)) for x, y in pts)
        ring_counts.append(len(pts))

    if not ring_counts or sum(ring_counts) < 3:
        return [], []

    verts_arr = np.asarray(coords, dtype=np.float64)
    ends = np.cumsum(np.asarray(ring_counts, dtype=np.uint32), dtype=np.uint32)
    indices = earcut.triangulate_float64(verts_arr, ends)

    faces = [
        (int(indices[i]), int(indices[i + 1]), int(indices[i + 2]))
        for i in range(0, len(indices), 3)
    ]
    return coords, faces


def to_mesh_cm(
    verts_m: List[Point2D],
    faces: List[Face],
    z_m: float,
) -> Tuple[List[Point3D], List[int]]:
    """XYZ centimeters; face indices flattened later in USD writer."""
    z_cm = z_m * CM_PER_M
    pts = [(x * CM_PER_M, y * CM_PER_M, z_cm) for x, y in verts_m]
    flat: List[int] = []
    for a, b, c in faces:
        flat.extend((a, b, c))
    return pts, flat


def repair_polygon(geom: BaseGeometry) -> BaseGeometry | None:
    """buffer(0) / make_valid; None if still empty."""
    if geom is None or geom.is_empty:
        return None
    if getattr(geom, "is_valid", True):
        return geom
    fixed = None
    try:
        from shapely import make_valid

        fixed = make_valid(geom)
    except Exception:
        fixed = None
    if fixed is None or getattr(fixed, "is_empty", True):
        try:
            fixed = geom.buffer(0)
        except Exception:
            return None
    if fixed is None or fixed.is_empty:
        return None
    if not getattr(fixed, "is_valid", True):
        try:
            fixed = fixed.buffer(0)
        except Exception:
            return None
    if fixed is None or fixed.is_empty or not getattr(fixed, "is_valid", True):
        return None
    return fixed


def difference_safe(geom: BaseGeometry, cutter: BaseGeometry) -> BaseGeometry:
    """geom.difference(cutter); return empty result; original only on exception."""
    if geom is None or geom.is_empty:
        return geom
    if cutter is None or cutter.is_empty:
        return geom
    try:
        result = geom.difference(cutter)
    except Exception:
        return geom
    if result is None:
        return geom
    return result
