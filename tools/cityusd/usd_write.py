from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

from cityusd.types import RasterMeta

try:
    from cityusd.cull import CULL_BUILDING_M, mesh_cull_custom_data
except ImportError:  # pragma: no cover
    CULL_BUILDING_M = 1200.0

    def mesh_cull_custom_data(end_m: float) -> dict:
        return {"cull_distance_m": float(end_m), "cull_distance_cm": float(end_m) * 100.0}

METERS_PER_UNIT = 0.01


def _planar_uvs(points_cm, tile: float = 2000.0) -> list:
    """Project UVs onto the two axes with the largest extents (so vertical boards get YZ)."""
    if not points_cm:
        return []
    xs = [float(p[0]) for p in points_cm]
    ys = [float(p[1]) for p in points_cm]
    zs = [float(p[2]) if len(p) > 2 else 0.0 for p in points_cm]
    spans = [
        (0, max(xs) - min(xs)),
        (1, max(ys) - min(ys)),
        (2, max(zs) - min(zs)),
    ]
    spans.sort(key=lambda t: t[1], reverse=True)
    ia, ib = spans[0][0], spans[1][0]
    a_vals = [float(p[ia]) if ia < len(p) else 0.0 for p in points_cm]
    b_vals = [float(p[ib]) if ib < len(p) else 0.0 for p in points_cm]
    amin, amax = min(a_vals), max(a_vals)
    bmin, bmax = min(b_vals), max(b_vals)
    da = (amax - amin) if amax != amin else 1.0
    db = (bmax - bmin) if bmax != bmin else 1.0
    return [((a - amin) / da, (b - bmin) / db) for a, b in zip(a_vals, b_vals)]


def configure_stage(path: Path) -> Usd.Stage:
    """Create a new USDA/USDC stage: cm units, Z-up, defaultPrim /World."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, METERS_PER_UNIT)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    return stage


def write_mesh(
    stage,
    path: str,
    points_cm,
    face_counts,
    face_indices,
    material_path: Optional[str],
    uvs=None,
    display_color=None,
    subsets=None,
    double_sided: bool = True,
) -> None:
    mesh = UsdGeom.Mesh.Define(stage, path)
    pts = []
    for p in points_cm:
        x = float(p[0])
        y = float(p[1])
        z = float(p[2]) if len(p) > 2 else 0.0
        pts.append(Gf.Vec3f(x, y, z))
    mesh.CreatePointsAttr(pts)
    mesh.CreateFaceVertexCountsAttr([int(c) for c in face_counts])
    mesh.CreateFaceVertexIndicesAttr([int(i) for i in face_indices])
    mesh.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    mesh.CreateDoubleSidedAttr(True if double_sided else False)
    if uvs is None:
        uvs = _planar_uvs(points_cm)
    if uvs:
        st = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
            "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex
        )
        st.Set([Gf.Vec2f(float(uv[0]), float(uv[1])) for uv in uvs])
    if display_color is not None:
        mesh.CreateDisplayColorAttr(
            [Gf.Vec3f(float(display_color[0]), float(display_color[1]), float(display_color[2]))]
        )
    if material_path:
        mat = UsdShade.Material.Get(stage, material_path)
        if mat and mat.GetPrim().IsValid():
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
    if subsets:
        for name, payload in subsets.items():
            face_ids, sub_mat = payload[0], payload[1]
            subset = UsdGeom.Subset.CreateGeomSubset(
                mesh,
                name,
                UsdGeom.Tokens.face,
                [int(i) for i in face_ids],
                familyName="materialBind",
            )
            if sub_mat:
                smat = UsdShade.Material.Get(stage, sub_mat)
                if smat and smat.GetPrim().IsValid():
                    UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(smat)


def write_point_instancer(
    stage,
    path: str,
    proto_prim_path,
    positions_cm,
    yaws_rad,
    proto_indices=None,
    cull_custom_data: Optional[dict] = None,
) -> None:
    instancer = UsdGeom.PointInstancer.Define(stage, path)
    proto_paths = [proto_prim_path] if isinstance(proto_prim_path, str) else list(proto_prim_path)
    instancer.CreatePrototypesRel().SetTargets(proto_paths)
    positions_cm = list(positions_cm)
    n = len(positions_cm)
    positions = []
    for p in positions_cm:
        x = float(p[0])
        y = float(p[1])
        z = float(p[2]) if len(p) > 2 else 0.0
        positions.append(Gf.Vec3f(x, y, z))
    if proto_indices is None:
        proto_indices = [0] * n
    instancer.CreateProtoIndicesAttr([int(i) for i in proto_indices[:n]])
    instancer.CreatePositionsAttr(positions)
    yaws = list(yaws_rad) if yaws_rad is not None else []
    if len(yaws) < n:
        yaws.extend([0.0] * (n - len(yaws)))
    orients = []
    for yaw in yaws[:n]:
        half = float(yaw) * 0.5
        orients.append(Gf.Quath(math.cos(half), 0.0, 0.0, math.sin(half)))
    instancer.CreateOrientationsAttr(orients)
    instancer.CreateScalesAttr([Gf.Vec3f(1.0, 1.0, 1.0)] * n)
    if cull_custom_data:
        prim = instancer.GetPrim()
        existing = dict(prim.GetCustomData() or {})
        existing.update(cull_custom_data)
        prim.SetCustomData(existing)


def write_placeholder_prototype(
    stage, path: str, verts, faces, material_path=None, display_color=None, uvs=None, double_sided: bool = True
) -> None:
    counts = [len(face) for face in faces]
    indices = [int(i) for face in faces for i in face]
    write_mesh(
        stage,
        path,
        verts,
        counts,
        indices,
        material_path,
        uvs=uvs,
        display_color=display_color,
        double_sided=double_sided,
    )


def reference_prototype_layer(stage, prim_path: str, layer_rel: str) -> None:
    """Compose models/prototypes/*.usda onto a PointInstancer prototype prim."""
    xf = UsdGeom.Xform.Define(stage, prim_path)
    xf.GetPrim().GetReferences().AddReference(layer_rel)


def write_prototype_layer(path: Path, prim_name: str, verts, faces, material_path=None, display_color=None) -> None:
    """Standalone prototype USDA; defaultPrim is the named Xform (swap-friendly)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, METERS_PER_UNIT)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    xf = UsdGeom.Xform.Define(stage, f"/{prim_name}")
    stage.SetDefaultPrim(xf.GetPrim())
    write_placeholder_prototype(
        stage, f"/{prim_name}/Geom", verts, faces, material_path, display_color
    )
    stage.GetRootLayer().Save()


def write_multipart_prototype_layer(path: Path, prim_name: str, parts: list[dict]) -> None:
    """parts: {name, verts, faces, material_path, display_color, texture_path, roughness, emissive_rgb}."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, METERS_PER_UNIT)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    xf = UsdGeom.Xform.Define(stage, f"/{prim_name}")
    stage.SetDefaultPrim(xf.GetPrim())
    for part in parts:
        mat_path = part.get("material_path")
        wrap = "clamp" if part.get("name") == "Board" else "repeat"
        if mat_path and part.get("texture_path"):
            write_preview_material(
                stage,
                mat_path,
                part.get("display_color") or (0.5, 0.5, 0.5),
                texture_path=part["texture_path"],
                roughness=float(part.get("roughness", 0.8)),
                emissive_rgb=part.get("emissive_rgb"),
                wrap=wrap,
            )
        elif mat_path:
            write_preview_material(
                stage,
                mat_path,
                part.get("display_color") or (0.5, 0.5, 0.5),
                roughness=float(part.get("roughness", 0.8)),
                emissive_rgb=part.get("emissive_rgb"),
                wrap=wrap,
            )
        write_placeholder_prototype(
            stage,
            f"/{prim_name}/{part['name']}",
            part["verts"],
            part["faces"],
            material_path=mat_path,
            display_color=part.get("display_color"),
            uvs=part.get("uvs"),
            double_sided=bool(part.get("double_sided", part.get("name") != "Board")),
        )
    stage.GetRootLayer().Save()


def write_preview_material(
    stage,
    path: str,
    diffuse_rgb=(0.5, 0.5, 0.5),
    texture_path: Optional[str] = None,
    roughness: float = 0.8,
    emissive_rgb=None,
    wrap: str = "repeat",
    opacity_from_alpha: bool = False,
) -> None:
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/PreviewSurface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(float(roughness))
    if texture_path:
        st_reader = UsdShade.Shader.Define(stage, f"{path}/PrimvarST")
        st_reader.CreateIdAttr("UsdPrimvarReader_float2")
        st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        tex = UsdShade.Shader.Define(stage, f"{path}/DiffuseTex")
        tex.CreateIdAttr("UsdUVTexture")
        tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_path)
        tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            st_reader.ConnectableAPI(), "result"
        )
        tex.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set(wrap)
        tex.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set(wrap)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
            tex.ConnectableAPI(), "rgb"
        )
        if opacity_from_alpha:
            shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(
                tex.ConnectableAPI(), "a"
            )
            shader.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(0.15)
    else:
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(float(diffuse_rgb[0]), float(diffuse_rgb[1]), float(diffuse_rgb[2]))
        )
    if emissive_rgb is not None:
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(float(emissive_rgb[0]), float(emissive_rgb[1]), float(emissive_rgb[2]))
        )
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")


def write_stripe_png(
    path: Path,
    stripe_rgb: tuple[int, int, int],
    bg_rgb: tuple[int, int, int] = (40, 40, 40),
) -> Path:
    from PIL import Image

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (8, 8), bg_rgb)
    pixels = img.load()
    for y in range(8):
        for x in range(8):
            if (x // 2) % 2 == 0:
                pixels[x, y] = stripe_rgb
    img.save(path)
    return path


def write_solid_marking_png(path: Path, rgb: tuple[int, int, int]) -> Path:
    from PIL import Image

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), rgb).save(path)
    return path


def ensure_marking_textures(textures_dir: Path) -> dict[str, Path]:
    textures_dir = Path(textures_dir)
    return {
        "yellow": write_solid_marking_png(textures_dir / "marking_yellow.png", (255, 204, 0)),
        "white": write_solid_marking_png(textures_dir / "marking_white.png", (255, 255, 255)),
    }


def _cell_token(i: int) -> str:
    """USD identifiers cannot contain '-' (negative cell indices)."""
    return f"n{abs(int(i))}" if int(i) < 0 else str(int(i))


def extract_face_submesh(points_cm, face_counts, face_indices, uvs, face_ids):
    """Keep only the listed faces; reindex points/UVs compactly."""
    counts = [int(c) for c in face_counts]
    indices = [int(i) for i in face_indices]
    offsets = [0]
    for c in counts:
        offsets.append(offsets[-1] + c)
    remap: dict[int, int] = {}
    new_pts: list = []
    new_uvs: list | None = [] if uvs is not None else None
    new_counts: list[int] = []
    new_idx: list[int] = []
    n_faces = len(counts)
    for fi in face_ids:
        fi = int(fi)
        if fi < 0 or fi >= n_faces:
            continue
        c = counts[fi]
        start = offsets[fi]
        new_counts.append(c)
        for k in range(c):
            old = indices[start + k]
            if old not in remap:
                remap[old] = len(new_pts)
                new_pts.append(points_cm[old])
                if new_uvs is not None:
                    new_uvs.append(uvs[old] if old < len(uvs) else (0.0, 0.0))
            new_idx.append(remap[old])
    return new_pts, new_counts, new_idx, new_uvs


def save_layer_atomic(stage, dest: Path) -> Path:
    """Save the stage, then replace dest. If dest is locked, keep the scratch file."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage.GetRootLayer().Save()
    ident = Path(stage.GetRootLayer().realPath or stage.GetRootLayer().identifier)
    try:
        if ident.resolve() == dest.resolve():
            return dest
    except OSError:
        pass
    try:
        if dest.exists():
            dest.unlink()
        ident.replace(dest)
        return dest
    except OSError as exc:
        print(f"warning: could not replace {dest} ({exc}); left {ident}", flush=True)
        return ident


BUILDING_MATERIAL_PATH = "/World/Looks/Building"


def write_building_cell(
    stage,
    ix: int,
    iy: int,
    lod_meshes: dict,
    switch_distance_m=0.0,
    cell_size_m: float = 400.0,
    material_path: Optional[str] = BUILDING_MATERIAL_PATH,
    suffix: str = "",
) -> str:
    cs = int(round(float(cell_size_m)))
    extra = f"_{suffix}" if suffix else ""
    if cs == 200:
        parent_path = f"/World/City/Buildings/c{_cell_token(ix)}_{_cell_token(iy)}{extra}"
    else:
        parent_path = f"/World/City/Buildings/c{cs}_{_cell_token(ix)}_{_cell_token(iy)}{extra}"
    parent = UsdGeom.Xform.Define(stage, parent_path)
    cull_cd = mesh_cull_custom_data(CULL_BUILDING_M)
    parent_cd = {
        "switch_distance_m": switch_distance_m,
        "cell_size_m": float(cs),
        "lod": ["LOD0", "LOD1", "LOD2"],
        "switch_distance_m_lod": {"LOD0": 0.0, "LOD1": 1500.0, "LOD2": 6000.0},
        "building_mesh_mode": "closed_mesh_geomsubset",
    }
    parent_cd.update(cull_cd)
    parent.GetPrim().SetCustomData(parent_cd)
    lod_switch = {"LOD0": 0.0, "LOD1": 1500.0, "LOD2": 6000.0}
    for name in ("LOD0", "LOD1", "LOD2"):
        mesh = lod_meshes.get(name) if lod_meshes else None
        if not mesh:
            continue
        points_cm, face_counts, face_indices = mesh[0], mesh[1], mesh[2]
        uvs = mesh[3] if len(mesh) > 3 else None
        mat = mesh[4] if len(mesh) > 4 and mesh[4] else material_path
        color = mesh[5] if len(mesh) > 5 else None
        subsets = mesh[6] if len(mesh) > 6 else None
        mesh_path = f"{parent_path}/{name}"
        # One closed mesh: Walls/Roof share geometry; materials via GeomSubset.
        # (Splitting into LOD0 + LOD0_Roof doubles Mesh/draw/BLAS count.)
        write_mesh(
            stage,
            mesh_path,
            points_cm,
            face_counts,
            face_indices,
            mat,
            uvs=uvs,
            display_color=color,
            subsets=subsets,
            double_sided=True,
        )
        prim = stage.GetPrimAtPath(mesh_path)
        if prim and prim.IsValid():
            mesh_cd = {
                "lodLevel": int(name[-1]),
                "switch_distance_m": lod_switch[name],
                "meshParts": "Walls+Roof",
            }
            mesh_cd.update(cull_cd)
            prim.SetCustomData(mesh_cd)
    return parent_path


def write_environment_layer(path: Path) -> None:
    stage = configure_stage(path)
    UsdGeom.Xform.Define(stage, "/World/Environment")
    stage.GetRootLayer().Save()


def write_terrain_layer(
    path: Path,
    heightmap_rel: Optional[str],
    ortho_rel: Optional[str],
    meta: Optional[RasterMeta],
) -> None:
    stage = configure_stage(path)
    xf = UsdGeom.Xform.Define(stage, "/World/Terrain")
    prim = xf.GetPrim()
    custom = {
        "heightmap_png": heightmap_rel or "",
        "ortho_png": ortho_rel or "",
        "alignment_json": "./terrain_src/alignment.json",
    }
    if meta is not None:
        custom["crs_epsg"] = int(meta.crs_epsg)
        custom["range_source"] = meta.range_source
    prim.SetCustomData(custom)
    _write_invisible_plane(stage, "/World/Terrain/RefPlane")
    stage.GetRootLayer().Save()


def write_nav_layer(
    path: Path,
    pgm_rel: Optional[str],
    yaml_rel: Optional[str],
    cost_rel: Optional[str] = None,
) -> None:
    stage = configure_stage(path)
    xf = UsdGeom.Xform.Define(stage, "/World/Nav")
    xf.GetPrim().SetCustomData(
        {
            "map_pgm": pgm_rel or "",
            "map_yaml": yaml_rel or "",
            "cost_pgm": cost_rel or (pgm_rel or "").replace("map.pgm", "cost.pgm"),
            "alignment_json": "./terrain_src/alignment.json",
        }
    )
    _write_invisible_plane(stage, "/World/Nav/RefPlane")
    stage.GetRootLayer().Save()


def _write_invisible_plane(stage, path: str, z_cm: float = -1.0) -> None:
    mesh = UsdGeom.Mesh.Define(stage, path)
    half = 0.5
    mesh.CreatePointsAttr(
        [
            Gf.Vec3f(-half, -half, z_cm),
            Gf.Vec3f(half, -half, z_cm),
            Gf.Vec3f(half, half, z_cm),
            Gf.Vec3f(-half, half, z_cm),
        ]
    )
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    mesh.CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
