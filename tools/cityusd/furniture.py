from __future__ import annotations

import math
from typing import Iterable, List, Tuple

from shapely.geometry import LineString

from cityusd.osm_parse import OsmData, OsmWay
from cityusd.roads import way_width_m
from cityusd.types import CM_PER_M

LAMP_HIGHWAYS = frozenset({"primary", "trunk", "motorway"})
LAMP_LATERAL_EXTRA_M = 0.4
MAX_SIGN_NAMES = 80

Point3D = Tuple[float, float, float]
Face = Tuple[int, int, int]


def tree_instances(data: OsmData) -> list[tuple[float, float, float]]:
    """natural=tree nodes → (x, y, yaw=0)."""
    out: list[tuple[float, float, float]] = []
    if data is None or not data.nodes:
        return out
    for node in data.nodes:
        if node.tags.get("natural") != "tree":
            continue
        x, y = node.xy_m
        out.append((float(x), float(y), 0.0))
    return out


def lamp_instances(
    motor_ways: list[OsmWay],
    spacing_m: float = 40.0,
) -> list[tuple[float, float, float]]:
    """primary/trunk/motorway only; both sides; spacing default 30; offset width/2+0.4m."""
    out: list[tuple[float, float, float]] = []
    if not motor_ways or spacing_m <= 0:
        return out
    for way in motor_ways:
        hwy = way.tags.get("highway", "")
        if hwy not in LAMP_HIGHWAYS:
            continue
        if way.coords_m is None or len(way.coords_m) < 2:
            continue
        line = LineString(way.coords_m)
        if line.is_empty or line.length <= 0:
            continue
        width = way_width_m(way.tags)
        lateral = width / 2.0 + LAMP_LATERAL_EXTRA_M
        for dist in _sample_distances(line.length, spacing_m):
            xy, yaw = _point_and_yaw(line, dist)
            if xy is None:
                continue
            dx, dy = math.cos(yaw), math.sin(yaw)
            # Left: (-dy, dx); right: (dy, -dx)
            for sign in (1.0, -1.0):
                rx = xy[0] + sign * dy * lateral
                ry = xy[1] - sign * dx * lateral
                out.append((rx, ry, yaw))
    return out


def placeholder_tree_mesh() -> tuple[list, list]:
    """Cylinder r=0.15m h=1.2m + cone r=1.2m h=2.5m; verts/faces in centimeters."""
    return _merge_parts(placeholder_tree_parts())


def placeholder_lamp_mesh() -> tuple[list, list]:
    """Cylinder r=0.08m h=6m + 0.3m cube on top; verts/faces in centimeters."""
    return _merge_parts(placeholder_lamp_parts())


def _merge_parts(parts: list[dict]) -> tuple[list, list]:
    verts: List[Point3D] = []
    faces: List[Face] = []
    for part in parts:
        off = len(verts)
        verts.extend(part["verts"])
        faces.extend((a + off, b + off, c + off) for a, b, c in part["faces"])
    return verts, faces


def placeholder_tree_parts() -> list[dict]:
    trunk_v: List[Point3D] = []
    trunk_f: List[Face] = []
    crown_v: List[Point3D] = []
    crown_f: List[Face] = []
    _append_cylinder(trunk_v, trunk_f, radius_m=0.18, height_m=1.4, z0_m=0.0, segments=10)
    _append_cone(crown_v, crown_f, radius_m=1.3, height_m=2.8, z0_m=1.2, segments=10)
    return [
        {"name": "Trunk", "verts": trunk_v, "faces": trunk_f, "display_color": (0.36, 0.22, 0.12)},
        {"name": "Crown", "verts": crown_v, "faces": crown_f, "display_color": (0.14, 0.48, 0.16)},
    ]


def placeholder_lamp_parts() -> list[dict]:
    """Cobra-head lamp scaled to the name-board (~4.2 m post), not a full 8 m highway mast."""
    base_v: List[Point3D] = []
    base_f: List[Face] = []
    _append_box_extents(base_v, base_f, -0.16, 0.16, -0.16, 0.16, 0.0, 0.10)
    _append_cylinder(base_v, base_f, radius_m=0.11, height_m=0.16, z0_m=0.08, segments=16)
    pole_v: List[Point3D] = []
    pole_f: List[Face] = []
    _append_cylinder(pole_v, pole_f, radius_m=0.055, height_m=2.10, z0_m=0.20, segments=16)
    _append_cylinder(pole_v, pole_f, radius_m=0.045, height_m=1.70, z0_m=2.25, segments=16)
    collar_v: List[Point3D] = []
    collar_f: List[Face] = []
    _append_cylinder(collar_v, collar_f, radius_m=0.08, height_m=0.12, z0_m=3.88, segments=12)
    _append_cylinder(collar_v, collar_f, radius_m=0.03, height_m=0.16, z0_m=3.98, segments=8)
    arm_v: List[Point3D] = []
    arm_f: List[Face] = []
    head_v: List[Point3D] = []
    head_f: List[Face] = []
    glass_v: List[Point3D] = []
    glass_f: List[Face] = []
    for side in (-1.0, 1.0):
        for k in range(6):
            t0 = k / 6.0
            t1 = (k + 1) / 6.0
            y0 = side * (0.10 + 0.85 * t0)
            y1 = side * (0.10 + 0.85 * t1)
            z0 = 3.95 - 0.28 * (t0 * t0)
            z1 = 3.95 - 0.28 * (t1 * t1)
            _append_box_extents(
                arm_v,
                arm_f,
                -0.035,
                0.035,
                min(y0, y1) - 0.02,
                max(y0, y1) + 0.02,
                min(z0, z1) - 0.025,
                max(z0, z1) + 0.025,
            )
        ye = side * 0.95
        zh = 3.95 - 0.28
        _append_box_extents(head_v, head_f, -0.11, 0.11, ye - 0.26, ye + 0.12, zh - 0.05, zh + 0.09)
        _append_box_extents(head_v, head_f, -0.08, 0.08, ye - 0.34, ye - 0.10, zh - 0.03, zh + 0.06)
        start = len(glass_v)
        _append_cylinder(glass_v, glass_f, radius_m=0.09, height_m=0.07, z0_m=zh - 0.11, segments=12)
        _translate_from(glass_v, start, 0.0, ye - 0.06, 0.0)
    return [
        {"name": "Base", "verts": base_v, "faces": base_f, "display_color": (0.22, 0.22, 0.24)},
        {"name": "Pole", "verts": pole_v, "faces": pole_f, "display_color": (0.16, 0.16, 0.18)},
        {"name": "Collar", "verts": collar_v, "faces": collar_f, "display_color": (0.28, 0.28, 0.30)},
        {"name": "Arm", "verts": arm_v, "faces": arm_f, "display_color": (0.16, 0.16, 0.18)},
        {"name": "Head", "verts": head_v, "faces": head_f, "display_color": (1.0, 0.84, 0.25)},
        {"name": "Glass", "verts": glass_v, "faces": glass_f, "display_color": (1.0, 0.92, 0.55)},
    ]


def sign_label(name: str) -> str:
    from cityusd.zh_simp import to_simplified

    text = to_simplified((name or "").strip())
    return text[:14] if text else ""


def placeholder_sign_parts() -> list[dict]:
    """Name board in YZ (normal +X). Board faces use 0-1 UVs so the texture is not striped."""
    post_v: List[Point3D] = []
    post_f: List[Face] = []
    board_v: List[Point3D] = []
    board_f: List[Face] = []
    board_uv: list[tuple[float, float]] = []
    cap_v: List[Point3D] = []
    cap_f: List[Face] = []
    _append_box_extents(post_v, post_f, -0.08, 0.08, -0.08, 0.08, 0.0, 4.20)
    _append_sign_board_faces(board_v, board_f, board_uv, -0.10, 0.10, -1.30, 1.30, 2.20, 3.85)
    _append_box_extents(cap_v, cap_f, -0.12, 0.12, -1.36, 1.36, 3.78, 3.98)
    return [
        {"name": "Post", "verts": post_v, "faces": post_f, "display_color": (0.16, 0.16, 0.18)},
        {
            "name": "Board",
            "verts": board_v,
            "faces": board_f,
            "uvs": board_uv,
            "display_color": (0.08, 0.32, 0.72),
            "double_sided": False,
        },
        {"name": "Cap", "verts": cap_v, "faces": cap_f, "display_color": (0.92, 0.92, 0.94)},
    ]


def _append_sign_board_faces(
    verts: List[Point3D],
    faces: List[Face],
    uvs: list,
    xmin_m: float,
    xmax_m: float,
    ymin_m: float,
    ymax_m: float,
    zmin_m: float,
    zmax_m: float,
) -> None:
    """Two large faces (front/back) with unique verts and 0-1 UVs."""
    for x, flip in ((xmax_m, False), (xmin_m, True)):
        corners = [
            (x * CM_PER_M, ymin_m * CM_PER_M, zmin_m * CM_PER_M),
            (x * CM_PER_M, ymax_m * CM_PER_M, zmin_m * CM_PER_M),
            (x * CM_PER_M, ymax_m * CM_PER_M, zmax_m * CM_PER_M),
            (x * CM_PER_M, ymin_m * CM_PER_M, zmax_m * CM_PER_M),
        ]
        # USD/OpenGL: V=0 is the image bottom. Board bottom (zmin) must get V=0
        # so painted text is upright, not flipped.
        face_uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        if flip:
            # Driver-facing face (look along +X): left is +Y, so ymax gets u=0.
            corners = [corners[1], corners[0], corners[3], corners[2]]
            face_uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        base = len(verts)
        verts.extend(corners)
        uvs.extend(face_uv)
        faces.append((base, base + 1, base + 2))
        faces.append((base, base + 2, base + 3))


def _translate_from(verts: List[Point3D], start: int, dx_m: float, dy_m: float, dz_m: float) -> None:
    dx, dy, dz = dx_m * CM_PER_M, dy_m * CM_PER_M, dz_m * CM_PER_M
    for i in range(start, len(verts)):
        x, y, z = verts[i]
        verts[i] = (x + dx, y + dy, z + dz)


def _sample_distances(length: float, spacing_m: float) -> Iterable[float]:
    if length <= spacing_m:
        return [length * 0.5]
    distances = []
    d = spacing_m
    while d < length:
        distances.append(d)
        d += spacing_m
    return distances


def _point_and_yaw(line: LineString, dist: float):
    if dist < 0:
        dist = 0.0
    elif dist > line.length:
        dist = line.length
    pt = line.interpolate(dist)
    delta = min(0.5, max(line.length * 0.01, 1e-3))
    a = line.interpolate(max(0.0, dist - delta))
    b = line.interpolate(min(line.length, dist + delta))
    dx, dy = b.x - a.x, b.y - a.y
    if math.hypot(dx, dy) < 1e-12:
        return None, None
    yaw = math.atan2(dy, dx)
    return (float(pt.x), float(pt.y)), yaw


def _append_cylinder(
    verts: List[Point3D],
    faces: List[Face],
    radius_m: float,
    height_m: float,
    z0_m: float,
    segments: int,
) -> None:
    r = radius_m * CM_PER_M
    z0 = z0_m * CM_PER_M
    z1 = (z0_m + height_m) * CM_PER_M
    base = len(verts)
    # bottom ring, top ring
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        x = r * math.cos(ang)
        y = r * math.sin(ang)
        verts.append((x, y, z0))
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        x = r * math.cos(ang)
        y = r * math.sin(ang)
        verts.append((x, y, z1))
    bot_center = base + 2 * segments
    top_center = bot_center + 1
    verts.append((0.0, 0.0, z0))
    verts.append((0.0, 0.0, z1))
    for i in range(segments):
        j = (i + 1) % segments
        b0, b1 = base + i, base + j
        t0, t1 = base + segments + i, base + segments + j
        faces.append((b0, b1, t1))
        faces.append((b0, t1, t0))
        faces.append((bot_center, b1, b0))
        faces.append((top_center, t0, t1))


def _append_cone(
    verts: List[Point3D],
    faces: List[Face],
    radius_m: float,
    height_m: float,
    z0_m: float,
    segments: int,
) -> None:
    r = radius_m * CM_PER_M
    z0 = z0_m * CM_PER_M
    z_tip = (z0_m + height_m) * CM_PER_M
    base = len(verts)
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        x = r * math.cos(ang)
        y = r * math.sin(ang)
        verts.append((x, y, z0))
    tip = base + segments
    bot_center = tip + 1
    verts.append((0.0, 0.0, z_tip))
    verts.append((0.0, 0.0, z0))
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((base + i, base + j, tip))
        faces.append((bot_center, base + j, base + i))


def _append_box(
    verts: List[Point3D],
    faces: List[Face],
    size_m: float,
    center_z_m: float,
) -> None:
    half = size_m / 2.0
    _append_box_extents(
        verts, faces, -half, half, -half, half, center_z_m - half, center_z_m + half
    )


def _append_box_extents(
    verts: List[Point3D],
    faces: List[Face],
    xmin_m: float,
    xmax_m: float,
    ymin_m: float,
    ymax_m: float,
    zmin_m: float,
    zmax_m: float,
) -> None:
    base = len(verts)
    corners = [
        (xmin_m * CM_PER_M, ymin_m * CM_PER_M, zmin_m * CM_PER_M),
        (xmax_m * CM_PER_M, ymin_m * CM_PER_M, zmin_m * CM_PER_M),
        (xmax_m * CM_PER_M, ymax_m * CM_PER_M, zmin_m * CM_PER_M),
        (xmin_m * CM_PER_M, ymax_m * CM_PER_M, zmin_m * CM_PER_M),
        (xmin_m * CM_PER_M, ymin_m * CM_PER_M, zmax_m * CM_PER_M),
        (xmax_m * CM_PER_M, ymin_m * CM_PER_M, zmax_m * CM_PER_M),
        (xmax_m * CM_PER_M, ymax_m * CM_PER_M, zmax_m * CM_PER_M),
        (xmin_m * CM_PER_M, ymax_m * CM_PER_M, zmax_m * CM_PER_M),
    ]
    verts.extend(corners)
    quads = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    for a, b, c, d in quads:
        faces.append((base + a, base + b, base + c))
        faces.append((base + a, base + c, base + d))
