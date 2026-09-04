"""CLI orchestrator: scan data → OSM city Scene Package."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

_TOOLS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _TOOLS_DIR.parent
for _p in (_TOOLS_DIR, _ROOT_DIR):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from shapely.geometry import Point, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from cityusd.buildings import (
    FLOOR_HEIGHT_M,
    LOD_LEVELS,
    building_height_m,
    carriageway_index,
    drop_enclosed_buildings,
    footprint_after_roads,
    group_buildings_for_lod,
)
from cityusd.crs import extent_from_lonlat_bbox, lonlat_to_utm, make_origin
from cityusd.furniture import (
    MAX_SIGN_NAMES,
    lamp_instances,
    placeholder_lamp_mesh,
    placeholder_sign_parts,
    sign_label,
    tree_instances,
)
from cityusd.facade_assets import ensure_facade_photos, ensure_roof_photos, photos_by_band
from cityusd.geom import repair_polygon, to_mesh_cm, triangulate_polygon
from cityusd.osm_parse import OsmWay, parse_osm
from cityusd.inbox_bind import bind_inbox_photos, resolve_asset_library_root
from cityusd.looks import (
    ROAD_DISPLAY_RGB,
    ROOF_VARIANT_COUNT,
    facade_band,
    facade_display_rgb,
    facade_material_path,
    facade_sheet_width_m,
    facade_tile_floors,
    facade_tile_uv_scale,
    facade_variant,
    facade_variant_count,
    road_display_rgb,
    road_texture_key,
    roof_display_rgb,
    roof_material_path,
)
from cityusd.package import (
    WORLD_SUBLAYERS,
    backup_existing_usd,
    build_package_meta,
    write_all_overlays,
    write_meta,
    write_prototype_files,
    write_world,
)
from cityusd.proc_textures import ensure_scene_textures, write_sign_board_png
from cityusd.nav_polys import collect_nav_polygons_connected
from cityusd.pgm import rasterize_pgm, write_nav2_yaml_bundle
from cityusd.nav2_paths import NAV2_CONNECTED
from cityusd.rasters import write_heightmap, write_ortho, write_terrain_alignment
from cityusd.roads import (
    MARKING_Z_M,
    arrow_decal_quad_cm,
    build_road_polygons,
    build_typed_junctions,
    clip_marking_to_road,
    graph_degree_from_ways,
    is_motor_highway,
    junction_arrows,
    marking_strip_polygons,
    motor_carriageway_polygons,
    point_in_disks,
    set_road_width_scale,
    sign_placements,
    split_line_coords_at_junctions,
    subtract_road_hierarchy,
    way_elevation_m,
    way_width_m,
    widths_along_piece,
)
from cityusd.scan_inputs import scan_data_dir
from cityusd.types import CM_PER_M, LAYER_Z_M, ExtentM, Origin
from cityusd.usd_write import (
    configure_stage,
    ensure_marking_textures,
    save_layer_atomic,
    write_building_cell,
    write_environment_layer,
    write_mesh,
    write_nav_layer,
    write_point_instancer,
    write_preview_material,
    write_placeholder_prototype,
    write_terrain_layer,
    reference_prototype_layer,
)
from cityusd.cull import (
    CULL_ARROW_END_M,
    CULL_ARROW_START_M,
    CULL_LAMP_END_M,
    CULL_LAMP_START_M,
    CULL_SIGN_END_M,
    CULL_SIGN_START_M,
    CULL_TREE_END_M,
    CULL_TREE_START_M,
    cull_policy_summary,
    instancer_cull_custom_data,
)
from cityusd.water_veg import vegetation_polygons, water_polygons
from pxr import UsdGeom


class BuildStats:
    def __init__(self) -> None:
        self.skipped = 0
        self.roads = 0
        self.buildings = 0
        self.water = 0
        self.vegetation = 0
        self.markings = 0
        self.arrows = 0
        self.signs = 0
        self.trees = 0
        self.lamps = 0
        self.junctions = 0


Mesh = tuple[list, list, list]


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    data_dir = Path(args.data)
    out_dir = Path(args.output)
    scale = float(getattr(args, "road_width_scale", 1.0) or 1.0)
    prev_scale = set_road_width_scale(scale)
    if abs(scale - 1.0) > 1e-9:
        print(f"road_width_scale={scale}", flush=True)
    try:
        return _main_impl(args, data_dir, out_dir)
    finally:
        set_road_width_scale(prev_scale)


def _main_impl(args: argparse.Namespace, data_dir: Path, out_dir: Path) -> int:
    found = scan_data_dir(data_dir)
    if found.osm is None:
        print("error: no OSM file found under --data; not writing output", file=sys.stderr)
        return 1

    print(f"scan: osm={found.osm}", flush=True)
    print(f"scan: dem={found.dem}", flush=True)
    print(f"scan: imagery={found.imagery}", flush=True)
    print(f"scan: assets={found.assets_dir}", flush=True)

    origin = None
    extent = None
    range_source = "osm_bbox"
    pipeline_mode = bool(getattr(args, "pipeline_mode", False))
    extent_json_path = getattr(args, "extent_json", None)

    if extent_json_path:
        from cityusd.pipeline.terrain import load_extent_context

        extent_file = Path(extent_json_path)
        package_dir = extent_file.parent
        _, origin, extent = load_extent_context(package_dir)
        range_source = "pipeline_extent"
    elif found.dem is not None:
        dem_origin, dem_extent = _origin_extent_from_dem(found.dem)
        if dem_origin is not None and dem_extent is not None:
            origin = dem_origin
            extent = dem_extent
            range_source = "dem"

    print(f"parse OSM ({found.osm.name}) origin={range_source} ...", flush=True)
    osm = parse_osm(found.osm, origin)
    if origin is None or extent is None:
        origin = osm.origin
        west, south, east, north = osm.lonlat_bbox
        extent = extent_from_lonlat_bbox(west, south, east, north, origin)
        range_source = "osm_bbox"
    n_bldg = sum(1 for w in osm.ways if "building" in w.tags)
    n_hwy = sum(1 for w in osm.ways if w.tags.get("highway"))
    print(
        f"OSM ways={len(osm.ways)} highways={n_hwy} buildings={n_bldg} "
        f"extent={extent.width:.1f}x{extent.height:.1f}m",
        flush=True,
    )

    scene_id = args.scene_id or f"{found.osm.stem}_{datetime.now().strftime('%Y%m%d')}"

    out_dir.mkdir(parents=True, exist_ok=True)
    layers_dir = out_dir / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)
    stats = BuildStats()
    layers = _layer_set(getattr(args, "layers", "all"))
    if pipeline_mode:
        layers -= {"nav", "terrain", "world"}
    print(f"layers: {','.join(sorted(layers))}", flush=True)
    if pipeline_mode:
        print("pipeline-mode: city geometry layers only (no nav/terrain/world/meta)", flush=True)
        zipped = None
    else:
        try:
            zipped = backup_existing_usd(out_dir, layers, scene_id)
        except Exception as exc:
            print(f"error: USD backup failed: {exc}", file=sys.stderr)
            return 1
        if zipped is not None:
            print(f"backup: {zipped.relative_to(out_dir)} ({zipped.stat().st_size} bytes)", flush=True)
        else:
            print("backup: no previous USD for these layers", flush=True)
    need_road_mesh = bool(layers & {"roads"})
    need_buildings = bool(layers & {"buildings", "nav"})
    need_water = bool(layers & {"water", "nav"})
    need_veg = bool(layers & {"vegetation", "nav"})
    need_lamps = "lamps" in layers
    need_signs = "signs" in layers

    heightmap_rel: Optional[str] = None
    ortho_rel: Optional[str] = None
    raster_meta = None
    hm_png = out_dir / "terrain_src" / "heightmap_16bit.png"
    ortho_png = out_dir / "terrain_src" / "ortho.png"
    if "terrain" not in layers:
        if hm_png.exists():
            heightmap_rel = "./terrain_src/heightmap_16bit.png"
        if ortho_png.exists():
            ortho_rel = "./terrain_src/ortho.png"
    else:
        if found.dem is not None:
            if args.reuse_rasters and hm_png.exists():
                print("reuse existing heightmap", flush=True)
                heightmap_rel = "./terrain_src/heightmap_16bit.png"
            else:
                print("heightmap ...", flush=True)
                try:
                    hm = write_heightmap(
                        found.dem,
                        origin,
                        extent,
                        hm_png,
                        out_dir / "terrain_src" / "heightmap_meta.json",
                    )
                    heightmap_rel = "./terrain_src/heightmap_16bit.png"
                    raster_meta = hm
                except Exception as exc:
                    print(f"warning: DEM heightmap skipped: {exc}", file=sys.stderr)
        else:
            print("warning: no DEM; skipping heightmap", file=sys.stderr)
        if found.imagery is not None:
            if args.reuse_rasters and ortho_png.exists():
                print("reuse existing ortho", flush=True)
                ortho_rel = "./terrain_src/ortho.png"
            else:
                print(f"ortho max_dim={int(args.ortho_max_dim)} ...", flush=True)
                try:
                    om = write_ortho(
                        found.imagery,
                        origin,
                        extent,
                        ortho_png,
                        out_dir / "terrain_src" / "ortho_meta.json",
                        max_dim=int(args.ortho_max_dim),
                    )
                    ortho_rel = "./terrain_src/ortho.png"
                    if raster_meta is None:
                        raster_meta = om
                except Exception as exc:
                    print(f"warning: imagery ortho skipped: {exc}", file=sys.stderr)
        else:
            print("warning: no imagery; skipping ortho", file=sys.stderr)

    def _refresh_alignment() -> None:
        nav_root = out_dir / f"{scene_id}-CostMap" / "2D" / NAV2_CONNECTED
        pgm_path = nav_root / "map.pgm"
        cost_path = nav_root / "cost.pgm"
        if not (heightmap_rel or ortho_rel or pgm_path.exists()):
            return
        align_path = write_terrain_alignment(
            out_dir / "terrain_src" / "alignment.json",
            scene_id=scene_id,
            origin=origin,
            extent=extent,
            heightmap_rel=heightmap_rel,
            ortho_rel=ortho_rel,
            pgm_rel=f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/map.pgm" if pgm_path.exists() else None,
            cost_rel=f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/cost.pgm" if cost_path.exists() else None,
            heightmap_meta_path=out_dir / "terrain_src" / "heightmap_meta.json",
            ortho_meta_path=out_dir / "terrain_src" / "ortho_meta.json",
            pgm_meta_path=nav_root / "map_meta.json",
        )
        print(f"terrain alignment: {align_path.relative_to(out_dir)}", flush=True)

    _refresh_alignment()

    highway_ways: list = []
    ranked: list = []
    typed_junctions: list = []
    junction_disks: list = []
    arrows: list = []
    building_items: list = []
    bldg_geoms: list = []
    water_polys: list = []
    veg_polys: list = []
    signs: list = []
    trees: list = []
    lamps: list = []
    graph_degree: dict = {}

    if need_road_mesh or need_lamps or need_signs:
        highway_ways = [w for w in osm.ways if w.tags.get("highway")]
    if need_road_mesh:
        print(f"roads: buffer {len(highway_ways)} ways ...", flush=True)
        buffered = build_road_polygons(highway_ways)
        print(f"roads: hierarchy cut {len(buffered)} polygons ...", flush=True)
        ranked = subtract_road_hierarchy(buffered)
        graph_degree = graph_degree_from_ways(highway_ways)
        print("roads: typed junctions ...", flush=True)
        typed_junctions = build_typed_junctions(highway_ways, graph_degree, buffered)
        typed_junctions = [j for j in typed_junctions if j.get("kind") in {"tee", "wye", "cross", "roundabout"}]
        junction_disks = [
            j["geom"]
            for j in typed_junctions
            if j.get("kind") in {"tee", "wye", "cross"} and j.get("geom") is not None
        ]
        stats.junctions = len(junction_disks)
        print(f"roads: junctions={stats.junctions} (marking gaps at nodes, no hull overlay)", flush=True)

    if need_buildings:
        if not highway_ways:
            highway_ways = [w for w in osm.ways if w.tags.get("highway")]
        road_lines, road_half, road_tree, road_pad = carriageway_index(highway_ways)
        print(
            f"buildings: drop if intersecting {len(road_lines)} carriageway segments (no pavement rebuild) ...",
            flush=True,
        )
        n_done = 0
        for way in osm.ways:
            if "building" not in way.tags:
                continue
            n_done += 1
            if n_done == 1 or n_done % 5000 == 0:
                print(f"buildings: {n_done}/{n_bldg} footprints ...", flush=True)
            try:
                fp = footprint_after_roads(
                    way,
                    road_lines,
                    road_tree=road_tree,
                    half_widths=road_half,
                    max_half=road_pad,
                )
            except Exception:
                stats.skipped += 1
                continue
            if fp is None or getattr(fp, "is_empty", True):
                continue
            building_items.append(
                {
                    "way": way,
                    "footprint": fp,
                    "height_m": building_height_m(way.tags),
                }
            )
        print(f"buildings: {len(building_items)} after dropping road overlaps", flush=True)
        before = len(building_items)
        building_items = drop_enclosed_buildings(building_items)
        print(
            f"buildings: {len(building_items)} after dropping enclosed ({before - len(building_items)} nested)",
            flush=True,
        )
        bldg_geoms = [it["footprint"] for it in building_items]

    if need_water or need_veg:
        cutter_parts = bldg_geoms
        if len(cutter_parts) > 5000 or not cutter_parts:
            print(
                f"water/veg: skip overlay cut ({len(cutter_parts)} cutters; city-scale)",
                flush=True,
            )
            water_polys = water_polygons(osm, None) if need_water else []
            veg_polys = vegetation_polygons(osm, None) if need_veg else []
        else:
            print(f"water/veg cutters: {len(cutter_parts)} indexed ...", flush=True)
            water_polys = water_polygons(osm, cutter_parts) if need_water else []
            veg_polys = vegetation_polygons(osm, cutter_parts) if need_veg else []
        print(f"water: {len(water_polys)} polygons", flush=True)
        print(f"veg: {len(veg_polys)} polygons", flush=True)

    if "roads" in layers:
        print("furniture/arrows/signs ...", flush=True)
        arrows = junction_arrows(ranked, graph_degree)
        if junction_disks:
            jtree = STRtree(junction_disks)
            arrows = [a for a in arrows if not point_in_disks(a["xy"], junction_disks, jtree)]
    if need_lamps or need_signs:
        if need_signs:
            signs = sign_placements(highway_ways)
        if need_lamps:
            lamps = lamp_instances(
                [w for w in highway_ways if w.tags.get("highway") in {"primary", "trunk", "motorway"}]
            )
    if need_veg:
        trees = tree_instances(osm)

    if "nav" in layers:
        print("nav PGM / costmap (connected) ...", flush=True)
        occupied, free = collect_nav_polygons_connected(osm)
        nav_dir = out_dir / f"{scene_id}-CostMap" / "2D" / NAV2_CONNECTED
        nav_dir.mkdir(parents=True, exist_ok=True)
        rasterize_pgm(
            extent,
            _flatten_polys(occupied),
            _flatten_polys(free),
            float(args.pgm_resolution),
            nav_dir / "map.pgm",
            nav_dir / "map_local.yaml",
            nav_dir / "map_meta.json",
            origin,
            range_source,
            free_all_touched=True,
            binary_occupancy=True,
            cost_same_as_map=True,
        )
        from cityusd.pgm import write_soft_edge_pgm

        write_soft_edge_pgm(
            nav_dir / "map.pgm",
            nav_dir / "map_soft.pgm",
            resolution_m=float(args.pgm_resolution),
            radius_m=2.0,
        )
        utm_e, utm_n = lonlat_to_utm(origin.lon, origin.lat, origin.epsg)
        write_nav2_yaml_bundle(
            nav_dir,
            extent=extent,
            extent_payload={
                "utm_abs_m": {"e0": utm_e, "n0": utm_n},
                "origin_wgs84": {"latitude": origin.lat, "longitude": origin.lon},
            },
            origin=origin,
            resolution_m=float(args.pgm_resolution),
            scene_id=scene_id,
        )
        _refresh_alignment()

    textures = ensure_marking_textures(out_dir / "textures")
    facade_photos: dict = {}
    roof_photos: list = []
    facade_uv_modes: dict = {}
    if "buildings" in layers:
        lib_root = resolve_asset_library_root(found.assets_dir, data_dir)
        if lib_root is not None:
            facade_photos, roof_photos, facade_uv_modes = bind_inbox_photos(lib_root)
        else:
            facade_photos, roof_photos, facade_uv_modes = {}, [], {}
        if facade_photos:
            n_src = sum(len(v) for v in facade_photos.values())
            print(
                f"facade/roof photos (AssetLibrary inbox @ {lib_root.name}, {n_src} sources) ...",
                flush=True,
            )
        else:
            print("facade/roof photos (CC0 ambientCG fallback) ...", flush=True)
            facade_cache = data_dir / "assets" / "facades"
            facade_photos = photos_by_band(ensure_facade_photos(facade_cache))
            roof_photos = ensure_roof_photos(facade_cache)
            facade_uv_modes = {}
    written_tex = ensure_scene_textures(
        out_dir / "textures",
        facade_photos=facade_photos,
        roof_photos=roof_photos,
        facade_uv_modes=facade_uv_modes,
    )
    uv_map = written_tex.pop("_facade_uv", {}) or {}
    layer_tex = {
        key: f"../textures/{path.relative_to(out_dir / 'textures').as_posix()}"
        for key, path in written_tex.items()
        if isinstance(path, Path)
    }
    layer_tex["yellow"] = "../textures/marking_yellow.png"
    layer_tex["white"] = "../textures/marking_white.png"
    if need_lamps or need_signs or need_veg:
        proto_tex = {
            key: f"../../textures/{written_tex[key].relative_to(out_dir / 'textures').as_posix()}"
            for key in ("bark", "foliage", "metal", "lamp_head", "sign_board")
            if key in written_tex
        }
        write_prototype_files(out_dir / "models", proto_tex)

    city_rels: dict[str, str] = {}
    if "water" in layers:
        print("USD city_water ...", flush=True)
        st, _p, rel = _create_city_layer(layers_dir, "city_water")
        _write_water_layer(st, water_polys, stats, layer_tex)
        st.GetRootLayer().Save()
        city_rels["city_water"] = rel
    if "vegetation" in layers:
        print("USD city_vegetation ...", flush=True)
        st, _p, rel = _create_city_layer(layers_dir, "city_vegetation")
        _write_vegetation_layer(st, veg_polys, trees, stats, layer_tex)
        st.GetRootLayer().Save()
        city_rels["city_vegetation"] = rel
    if "roads" in layers:
        print("USD city_roads ...", flush=True)
        st, _p, rel = _create_city_layer(layers_dir, "city_roads")
        _write_roads_layer(st, ranked, arrows, stats, layer_tex, typed_junctions, graph_degree)
        st.GetRootLayer().Save()
        city_rels["city_roads"] = rel
    if "buildings" in layers:
        print("USD city_buildings ...", flush=True)
        dest_b = layers_dir / "city_buildings.usdc"
        scratch_b = layers_dir / "city_buildings.scratch.usdc"
        try:
            st = configure_stage(scratch_b)
            rel = "./layers/city_buildings.usdc"
        except Exception as exc:
            print(f"warning: scratch buildings layer failed: {exc}", file=sys.stderr)
            st, dest_b, rel = _create_city_layer(layers_dir, "city_buildings")
        _write_buildings_layer(st, building_items, stats, layer_tex, uv_map)
        saved = save_layer_atomic(st, dest_b)
        if saved.resolve() != dest_b.resolve():
            rel = f"./layers/{saved.name}"
            world_path = out_dir / f"World_{scene_id}.usda"
            if world_path.is_file():
                text = world_path.read_text(encoding="utf-8")
                world_path.write_text(
                    text.replace("./layers/city_buildings.usdc", rel).replace(
                        "./layers/city_buildings.usda", rel
                    ),
                    encoding="utf-8",
                )
                print(f"world sublayer retargeted to {rel}", flush=True)
        city_rels["city_buildings"] = rel
    if "lamps" in layers:
        print("USD city_lamps ...", flush=True)
        st, _p, rel = _create_city_layer(layers_dir, "city_lamps")
        _write_lamps_layer(st, lamps, stats)
        st.GetRootLayer().Save()
        city_rels["city_lamps"] = rel
    if "signs" in layers:
        print("USD city_signs ...", flush=True)
        st, _p, rel = _create_city_layer(layers_dir, "city_signs")
        _write_signs_layer(st, signs, stats, out_dir / "textures")
        st.GetRootLayer().Save()
        city_rels["city_signs"] = rel

    if "world" in layers:
        write_environment_layer(layers_dir / "environment.usda")
    if "terrain" in layers:
        write_terrain_layer(
            layers_dir / "terrain.usda",
            heightmap_rel,
            ortho_rel,
            raster_meta,
        )
    if "nav" in layers:
        write_nav_layer(
            layers_dir / "nav.usda",
            f"../{scene_id}-CostMap/2D/{NAV2_CONNECTED}/map.pgm",
            f"../{scene_id}-CostMap/2D/{NAV2_CONNECTED}/map_local.yaml",
        )
    if "world" in layers:
        write_all_overlays(out_dir / "overlay")

        sublayers = []
        for item in WORLD_SUBLAYERS:
            replaced = item
            for stem, rel in city_rels.items():
                replaced = replaced.replace(f"./layers/{stem}.usdc", rel)
            sublayers.append(replaced)
        write_world(out_dir / f"World_{scene_id}.usda", scene_id, sublayers)

        crs = {
            "epsg": origin.epsg,
            "origin_wgs84": {
                "lon": origin.lon,
                "lat": origin.lat,
                "height_m": origin.height_m,
            },
            "extent_m": extent.to_json(),
            "range_source": range_source,
        }
        meta = build_package_meta(scene_id, crs=crs)
        meta["layers"].update(city_rels)
        meta["nav"] = {
            "map_pgm": f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/map.pgm",
            "map_yaml": f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/map_local.yaml",
            "map_yaml_utm": f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/map.yaml",
            "valhalla_origin": f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/valhalla_origin.yaml",
            "cost_pgm": f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/cost.pgm",
            "map_soft_pgm": f"./{scene_id}-CostMap/2D/{NAV2_CONNECTED}/map_soft.pgm",
        }
        write_meta(out_dir / "meta.json", meta)

        descriptions = [str(p) for p in found.descriptions]
        if args.description:
            for extra in args.description:
                descriptions.append(str(Path(extra)))
        sources = {
            "osm": str(found.osm),
            "dem": str(found.dem) if found.dem else None,
            "imagery": str(found.imagery) if found.imagery else None,
            "descriptions": descriptions,
            "asset_library": str(found.assets_dir) if found.assets_dir else None,
        }
        (out_dir / "sources_manifest.json").write_text(
            json.dumps(sources, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        assets_used = {
            "items": [
                {"name": "tree_placeholder", "source": "generated", "path": "./models/prototypes/tree.usda"},
                {"name": "lamp_placeholder", "source": "generated", "path": "./models/prototypes/lamp.usda"},
                {"name": "sign_placeholder", "source": "generated", "path": "./models/prototypes/sign.usda"},
                {"name": "marking_yellow", "source": "generated", "path": "./textures/marking_yellow.png"},
                {"name": "marking_white", "source": "generated", "path": "./textures/marking_white.png"},
            ]
            + [
                {"name": key, "source": "generated", "path": f"./textures/{path.relative_to(out_dir / 'textures').as_posix()}"}
                for key, path in written_tex.items()
            ]
        }
        for name, path in textures.items():
            _ = name, path
        (out_dir / "assets_used.json").write_text(
            json.dumps(assets_used, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif not pipeline_mode and ("lamps" in layers or "signs" in layers):
        sublayers = []
        for item in WORLD_SUBLAYERS:
            replaced = item
            for stem, rel in city_rels.items():
                replaced = replaced.replace(f"./layers/{stem}.usdc", rel)
            sublayers.append(replaced)
        write_world(out_dir / f"World_{scene_id}.usda", scene_id, sublayers)
        meta_path = out_dir / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            layers_meta = meta.setdefault("layers", {})
            layers_meta.pop("city_furniture", None)
            if "city_lamps" in city_rels:
                layers_meta["city_lamps"] = city_rels["city_lamps"]
            if "city_signs" in city_rels:
                layers_meta["city_signs"] = city_rels["city_signs"]
            meta["lamp_instancer"] = True
            meta["sign_instancer"] = True
            write_meta(meta_path, meta)

    if pipeline_mode:
        stats_payload = {
            "scene_id": scene_id,
            "range_source": range_source,
            "origin_wgs84": {"lon": origin.lon, "lat": origin.lat, "height_m": origin.height_m},
            "extent_m": extent.to_json(),
            "city_layers": city_rels,
            "stats": {
                "roads": stats.roads,
                "buildings": stats.buildings,
                "water": stats.water,
                "vegetation": stats.vegetation,
                "markings": stats.markings,
                "arrows": stats.arrows,
                "signs": stats.signs,
                "trees": stats.trees,
                "lamps": stats.lamps,
                "junctions": stats.junctions,
                "skipped": stats.skipped,
            },
        }
        (out_dir / "layers" / "city_build_stats.json").write_text(
            json.dumps(stats_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(
        f"Built {scene_id}: roads={stats.roads} buildings={stats.buildings} "
        f"water={stats.water} veg={stats.vegetation} markings={stats.markings} "
        f"arrows={stats.arrows} signs={stats.signs} trees={stats.trees} "
        f"lamps={stats.lamps} junctions={stats.junctions} skipped={stats.skipped}"
    )
    return 0


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build OSM City USD Scene Package")
    parser.add_argument("--data", required=True, help="Input data directory")
    parser.add_argument("--output", required=True, help="Scene Package output directory")
    parser.add_argument("--pgm-resolution", type=float, default=1.0)
    parser.add_argument("--ortho-max-dim", type=int, default=8192)
    parser.add_argument("--scene-id", default=None)
    parser.add_argument(
        "--reuse-rasters",
        action="store_true",
        help="Reuse existing heightmap/ortho PNG if present",
    )
    parser.add_argument(
        "--layers",
        default="all",
        help="Comma-separated layers to write: all, roads, buildings, water, vegetation, lamps, signs, furniture, nav, terrain, world",
    )
    parser.add_argument(
        "--description",
        action="append",
        default=None,
        help="Description JSON path (recorded only; overlays stay empty)",
    )
    parser.add_argument(
        "--extent-json",
        default=None,
        help="Pipeline extent.json path; use its origin/local extent instead of DEM/OSM bbox",
    )
    parser.add_argument(
        "--pipeline-mode",
        action="store_true",
        help="City geometry layers only for build_scene_pipeline (no nav/terrain/world/meta)",
    )
    parser.add_argument(
        "--road-width-scale",
        type=float,
        default=1.0,
        help="Multiply OSM/inferred road widths (and carriageway drop distance). Default 1.0",
    )
    return parser.parse_args(argv)


ALL_LAYER_KEYS = (
    "water",
    "vegetation",
    "roads",
    "buildings",
    "lamps",
    "signs",
    "nav",
    "terrain",
    "world",
)
_LAYER_ALIASES = {
    "city_water": "water",
    "city_vegetation": "vegetation",
    "city_roads": "roads",
    "city_buildings": "buildings",
    "city_lamps": "lamps",
    "city_signs": "signs",
    "city_furniture": "furniture",
    "trees": "vegetation",
}


def _layer_set(raw: Optional[str]) -> set[str]:
    text = (raw or "all").strip().lower()
    if text in {"all", "*"}:
        return set(ALL_LAYER_KEYS)
    out: set[str] = set()
    for part in text.split(","):
        key = _LAYER_ALIASES.get(part.strip(), part.strip())
        if key:
            out.add(key)
    if "furniture" in out:
        out.discard("furniture")
        out.add("lamps")
        out.add("signs")
    return out


def _origin_extent_from_dem(dem_path: Path) -> tuple[Optional[Origin], Optional[ExtentM]]:
    import rasterio
    from rasterio.warp import transform_bounds

    try:
        with rasterio.open(dem_path) as src:
            src_crs = src.crs or "EPSG:4326"
            west, south, east, north = transform_bounds(
                src_crs, "EPSG:4326", *src.bounds, densify_pts=21
            )
    except Exception as exc:
        print(f"warning: could not read DEM bounds: {exc}", file=sys.stderr)
        return None, None
    lon = (west + east) / 2.0
    lat = (south + north) / 2.0
    origin = make_origin(lon, lat)
    extent = extent_from_lonlat_bbox(west, south, east, north, origin)
    return origin, extent


def _iter_polygons(geom):
    if geom is None or getattr(geom, "is_empty", True):
        return
    gtype = getattr(geom, "geom_type", "")
    if gtype == "Polygon":
        yield geom
    elif gtype == "MultiPolygon":
        for g in geom.geoms:
            yield from _iter_polygons(g)
    elif gtype == "GeometryCollection":
        for g in geom.geoms:
            yield from _iter_polygons(g)


def _flatten_polys(geoms) -> list:
    out = []
    for g in geoms or []:
        out.extend(_iter_polygons(g))
    return out


def _concat_meshes(meshes: list) -> Optional[Mesh]:
    if not meshes:
        return None
    pts: list = []
    counts: list = []
    indices: list = []
    uvs: list = []
    offset = 0
    for m in meshes:
        p, c, i = m[0], m[1], m[2]
        uv = m[3] if len(m) > 3 and m[3] is not None else [
            (float(pt[0]) / 2000.0, float(pt[1]) / 2000.0) for pt in p
        ]
        pts.extend(p)
        counts.extend(c)
        indices.extend(idx + offset for idx in i)
        uvs.extend(uv)
        offset += len(p)
    return pts, counts, indices, uvs


def _flat_mesh(poly, z_m: float, stats: BuildStats) -> Optional[Mesh]:
    try:
        verts, faces = triangulate_polygon(poly)
    except Exception:
        stats.skipped += 1
        return None
    if not verts or not faces:
        stats.skipped += 1
        return None
    pts, flat = to_mesh_cm(verts, faces, z_m)
    uvs = [(p[0] / 2000.0, p[1] / 2000.0) for p in pts]
    return pts, [3] * len(faces), flat, uvs


def _cell_ij_from_geom(geom, size_m: float) -> tuple[int, int]:
    try:
        c = geom.centroid
        return int(math.floor(float(c.x) / size_m)), int(math.floor(float(c.y) / size_m))
    except Exception:
        return 0, 0


def _cell_prim(ix: int, iy: int) -> str:
    def tok(v: int) -> str:
        return f"n{abs(int(v))}" if int(v) < 0 else str(int(v))
    return f"c{tok(ix)}_{tok(iy)}"


def _extrude_building(
    poly,
    height_m: float,
    z0_m: float,
    stats: BuildStats,
    tile_floors: int = 1,
    uv_mode: str = "tile",
    sheet_width_m: float = 12.0,
) -> Optional[Mesh]:
    parts: list = []
    for p in _iter_polygons(poly):
        try:
            mesh = _extrude_one(p, height_m, z0_m, tile_floors, uv_mode, sheet_width_m)
        except Exception:
            stats.skipped += 1
            continue
        if mesh is None:
            stats.skipped += 1
            continue
        parts.append(mesh)
    return _concat_extrude(parts)


def _concat_extrude(parts: list) -> Optional[Mesh]:
    if not parts:
        return None
    pts: list = []
    counts: list = []
    indices: list = []
    uvs: list = []
    walls: list[int] = []
    roofs: list[int] = []
    v_off = 0
    f_off = 0
    for p, c, i, uv, wf, rf in parts:
        pts.extend(p)
        counts.extend(c)
        indices.extend(idx + v_off for idx in i)
        uvs.extend(uv)
        walls.extend(f + f_off for f in wf)
        roofs.extend(f + f_off for f in rf)
        v_off += len(p)
        f_off += len(c)
    return pts, counts, indices, uvs, walls, roofs


def _merged_wall_segments(ring) -> list[tuple[float, float, float, float]]:
    """Collapse collinear OSM nodes so one facade plane gets one unique-sheet quad."""
    pts = list(ring)
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 2:
        return []

    def edge_dir(a, b):
        dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            return None
        return dx / ln, dy / ln

    runs: list[tuple[float, float, float, float]] = []
    run_start = 0
    d0 = None
    while run_start < n and d0 is None:
        d0 = edge_dir(pts[run_start], pts[(run_start + 1) % n])
        if d0 is None:
            run_start += 1
    if d0 is None:
        return []
    ux, uy = d0
    i = run_start
    origin = run_start
    for _ in range(n):
        a = pts[i]
        nxt = (i + 1) % n
        d = edge_dir(a, pts[nxt])
        if d is None:
            i = nxt
            continue
        dx, dy = d
        collinear = abs(ux * dy - uy * dx) < 0.02 and (ux * dx + uy * dy) > 0.99
        if not collinear:
            x0, y0 = pts[run_start]
            if math.hypot(a[0] - x0, a[1] - y0) >= 0.05:
                runs.append((float(x0), float(y0), float(a[0]), float(a[1])))
            run_start = i
            ux, uy = dx, dy
        i = nxt
        if i == origin:
            break
    x0, y0 = pts[run_start]
    x1, y1 = pts[origin]
    if math.hypot(x1 - x0, y1 - y0) >= 0.05:
        runs.append((float(x0), float(y0), float(x1), float(y1)))
    return runs


def _extrude_one(
    poly, height_m: float, z0_m: float, tile_floors: int = 1, uv_mode: str = "tile", sheet_width_m: float = 12.0
):
    verts, faces = triangulate_polygon(poly)
    if not verts or not faces:
        return None
    z0 = z0_m * CM_PER_M
    z1 = (z0_m + float(height_m)) * CM_PER_M
    h_cm = float(height_m) * CM_PER_M
    pts: list = []
    uvs: list = []
    counts: list[int] = []
    indices: list[int] = []
    wall_faces: list[int] = []
    roof_faces: list[int] = []
    face_i = 0
    roof_tile = 1500.0
    roof_base = 0
    for x, y in verts:
        pts.append((x * CM_PER_M, y * CM_PER_M, z1))
        uvs.append((x * CM_PER_M / roof_tile, y * CM_PER_M / roof_tile))
    for a, b, c in faces:
        counts.append(3)
        indices.extend((roof_base + a, roof_base + b, roof_base + c))
        roof_faces.append(face_i)
        face_i += 1
    s = 0.0
    floors = max(1, int(tile_floors))
    if uv_mode == "unique_sheet":
        wall_u = max(4.0, float(sheet_width_m)) * CM_PER_M
        wall_v = FLOOR_HEIGHT_M * floors * CM_PER_M
    else:
        tile_scale = facade_tile_uv_scale()
        wall_u = 600.0 * tile_scale
        wall_v = FLOOR_HEIGHT_M * floors * CM_PER_M * tile_scale
    for x0, y0, x1, y1 in _merged_wall_segments(poly.exterior.coords):
        seg = math.hypot((x1 - x0) * CM_PER_M, (y1 - y0) * CM_PER_M)
        s1 = s + seg
        quad = [
            (x0 * CM_PER_M, y0 * CM_PER_M, z0),
            (x1 * CM_PER_M, y1 * CM_PER_M, z0),
            (x1 * CM_PER_M, y1 * CM_PER_M, z1),
            (x0 * CM_PER_M, y0 * CM_PER_M, z1),
        ]
        uquad = [
            (s / wall_u, 0.0),
            (s1 / wall_u, 0.0),
            (s1 / wall_u, h_cm / wall_v),
            (s / wall_u, h_cm / wall_v),
        ]
        base = len(pts)
        pts.extend(quad)
        uvs.extend(uquad)
        counts.append(4)
        indices.extend((base, base + 1, base + 2, base + 3))
        wall_faces.append(face_i)
        face_i += 1
        s = s1
    return pts, counts, indices, uvs, wall_faces, roof_faces


def _lod2_union_mesh(items: list, z0_m: float, stats: BuildStats) -> Optional[Mesh]:
    geoms = [
        it["footprint"]
        for it in items
        if it.get("footprint") is not None and not getattr(it["footprint"], "is_empty", True)
    ]
    if not geoms:
        return None
    try:
        merged = unary_union(geoms)
    except Exception:
        stats.skipped += 1
        return None
    if merged is None or getattr(merged, "is_empty", True):
        return None
    if not getattr(merged, "is_valid", True):
        merged = repair_polygon(merged)
        if merged is None or getattr(merged, "is_empty", True):
            return None
    height = max(float(it["height_m"]) for it in items)
    return _extrude_building(merged, height, z0_m, stats)


def _payload_from_extrude_safe(extruded, band: str, osm_id: int = 0):
    if extruded is None:
        return None
    return _payload_from_extrude(extruded, band, osm_id)


def _aabb_band_mesh(items: list, z0_m: float, stats: BuildStats, band: str):
    bounds = None
    height = 0.0
    for it in items:
        fp = it.get("footprint")
        if fp is None or getattr(fp, "is_empty", True):
            continue
        b = fp.bounds
        if bounds is None:
            bounds = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
        else:
            bounds[0] = min(bounds[0], float(b[0]))
            bounds[1] = min(bounds[1], float(b[1]))
            bounds[2] = max(bounds[2], float(b[2]))
            bounds[3] = max(bounds[3], float(b[3]))
        height = max(height, float(it["height_m"]))
    if bounds is None or height <= 0:
        return None
    poly = box(bounds[0], bounds[1], bounds[2], bounds[3])
    return _payload_from_extrude_safe(
        _extrude_building(poly, height, z0_m, stats, tile_floors=1), band, 0
    )


def _create_city_layer(layers_dir: Path, stem: str):
    """Prefer `.usdc`; fall back to `.usda`."""
    for name in (f"{stem}.usdc", f"{stem}.usda"):
        path = layers_dir / name
        try:
            stage = configure_stage(path)
            return stage, path, f"./layers/{name}"
        except Exception as exc:
            print(f"warning: could not create {name}: {exc}", file=sys.stderr)
    raise RuntimeError(f"unable to create layers/{stem}.usdc or .usda")


def _set_osm_data(stage, prim_path: str, payload: dict) -> None:
    prim = stage.GetPrimAtPath(prim_path)
    if prim and prim.IsValid():
        prim.SetCustomData(payload)


def _emit_flat(stage, path, combined, material, display_color=None, double_sided: bool = True) -> None:
    if combined is None:
        return
    uvs = combined[3] if len(combined) > 3 else None
    write_mesh(
        stage,
        path,
        combined[0],
        combined[1],
        combined[2],
        material,
        uvs=uvs,
        display_color=display_color,
        double_sided=double_sided,
    )


def _payload_from_extrude(extruded, band: str, osm_id: int = 0, tags: dict | None = None):
    pts, counts, indices, uvs, walls, roofs = extruded
    facade_mat = facade_material_path(band, osm_id, tags)
    roof_mat = roof_material_path(osm_id)
    return (
        pts,
        counts,
        indices,
        uvs,
        facade_mat,
        facade_display_rgb(band),
        {
            "Walls": (walls, facade_mat),
            "Roof": (roofs, roof_mat),
        },
    )


def _concat_band_extrudes(parts: list, band: str, osm_id: int = 0):
    merged = _concat_extrude(parts)
    if merged is None:
        return None
    return _payload_from_extrude(merged, band, osm_id)


def _write_water_layer(stage, water_polys, stats: BuildStats, tex: dict[str, str]) -> None:
    UsdGeom.Xform.Define(stage, "/World/City")
    UsdGeom.Xform.Define(stage, "/World/City/Water")
    write_preview_material(
        stage,
        "/World/Looks/Water",
        (0.18, 0.42, 0.68),
        texture_path=tex.get("water"),
        roughness=0.2,
    )
    z_water = LAYER_Z_M["water"]
    for i, geom in enumerate(water_polys):
        meshes = [_flat_mesh(p, z_water, stats) for p in _iter_polygons(geom)]
        meshes = [m for m in meshes if m]
        combined = _concat_meshes(meshes)
        if combined is None:
            continue
        _emit_flat(stage, f"/World/City/Water/w{i}", combined, "/World/Looks/Water", (0.12, 0.40, 0.66))
        stats.water += 1


def _write_vegetation_layer(stage, veg_polys, trees, stats: BuildStats, tex: dict[str, str]) -> None:
    UsdGeom.Xform.Define(stage, "/World/City")
    UsdGeom.Xform.Define(stage, "/World/City/Vegetation")
    UsdGeom.Xform.Define(stage, "/World/City/Vegetation/Areas")
    write_preview_material(
        stage,
        "/World/Looks/Vegetation",
        (0.28, 0.52, 0.24),
        texture_path=tex.get("grass"),
        roughness=1.0,
    )
    z_veg = LAYER_Z_M["vegetation"]
    for i, geom in enumerate(veg_polys):
        meshes = [_flat_mesh(p, z_veg, stats) for p in _iter_polygons(geom)]
        meshes = [m for m in meshes if m]
        combined = _concat_meshes(meshes)
        if combined is None:
            continue
        _emit_flat(
            stage,
            f"/World/City/Vegetation/Areas/v{i}",
            combined,
            "/World/Looks/Vegetation",
            (0.22, 0.48, 0.18),
        )
        stats.vegetation += 1
    tree_proto = "/World/City/Vegetation/Prototypes/TreePlaceholder"
    reference_prototype_layer(stage, tree_proto, "../models/prototypes/tree.usda")
    if trees:
        positions = [(x * CM_PER_M, y * CM_PER_M, 0.0) for x, y, _yaw in trees]
        yaws = [yaw for _x, _y, yaw in trees]
        write_point_instancer(
            stage,
            "/World/City/Vegetation/I_Trees",
            tree_proto,
            positions,
            yaws,
            cull_custom_data=instancer_cull_custom_data(CULL_TREE_START_M, CULL_TREE_END_M),
        )
        stats.trees = len(trees)


def _write_roads_layer(
    stage,
    ranked,
    arrows,
    stats: BuildStats,
    tex: dict[str, str],
    typed_junctions=None,
    graph_degree=None,
) -> None:
    UsdGeom.Xform.Define(stage, "/World/City")
    UsdGeom.Xform.Define(stage, "/World/City/Roads")
    UsdGeom.Xform.Define(stage, "/World/Looks")
    for key in ROAD_DISPLAY_RGB:
        write_preview_material(
            stage,
            f"/World/Looks/Road_{key}",
            ROAD_DISPLAY_RGB[key],
            texture_path=tex.get(key),
            roughness=0.85,
        )
    write_preview_material(stage, "/World/Looks/MarkingYellow", texture_path=tex["yellow"])
    write_preview_material(stage, "/World/Looks/MarkingWhite", texture_path=tex["white"])
    write_preview_material(
        stage,
        "/World/Looks/Arrow",
        (1.0, 1.0, 1.0),
        texture_path=tex.get("arrow_decal", tex.get("arrow_fill")),
        roughness=0.45,
        wrap="clamp",
        opacity_from_alpha=True,
    )

    z_road = LAYER_Z_M["roads"]
    j_points = []
    for key, deg in (graph_degree or {}).items():
        if int(deg) >= 3:
            j_points.append(Point(float(key[0]), float(key[1])))
    j_tree = STRtree(j_points) if j_points else None
    road_buckets: dict = defaultdict(list)
    for _i, (way, geom) in enumerate(ranked):
        key = road_texture_key(way.tags.get("highway", ""))
        z_m = z_road + way_elevation_m(way.tags)
        for poly in _iter_polygons(geom):
            m = _flat_mesh(poly, z_m, stats)
            if not m:
                continue
            ix, iy = _cell_ij_from_geom(poly, 400.0)
            road_buckets[(key, ix, iy, round(z_m, 3))].append(m)
    for (key, ix, iy, z_key), meshes in road_buckets.items():
        combined = _concat_meshes(meshes)
        if combined is None:
            continue
        mat = f"/World/Looks/Road_{key}"
        path = f"/World/City/Roads/{_cell_prim(ix, iy)}_{key}"
        if abs(z_key - z_road) > 0.05:
            zc = int(round(float(z_key) * 100.0))
            ztok = f"n{abs(zc)}" if zc < 0 else str(zc)
            path = f"{path}_e{ztok}"
        _emit_flat(stage, path, combined, mat, road_display_rgb(key))
        stats.roads += 1

    print("USD city_roads: markings ...", flush=True)
    UsdGeom.Xform.Define(stage, "/World/City/Roads/Markings")
    mark_buckets: dict = defaultdict(list)
    for way, _geom in ranked:
        if way.tags.get("highway") == "junction":
            continue
        if _geom is None or getattr(_geom, "is_empty", True):
            continue
        z_m = MARKING_Z_M + way_elevation_m(way.tags)
        width = way_width_m(way.tags)
        setback = max(3.0, width * 0.45)
        pieces = (
            split_line_coords_at_junctions(way.coords_m, j_points, j_tree, setback)
            if j_tree is not None
            else [way.coords_m]
        )
        for piece in pieces:
            vw = widths_along_piece(way, piece)
            for strip in marking_strip_polygons(piece, way.tags, width, vw):
                style = str(strip.get("style", ""))
                mat = "/World/Looks/MarkingYellow" if "yellow" in style else "/World/Looks/MarkingWhite"
                kind = "y" if "yellow" in style else "w"
                for poly in _iter_polygons(strip.get("geom")):
                    clipped = clip_marking_to_road(poly, _geom)
                    for part in _iter_polygons(clipped):
                        m = _flat_mesh(part, z_m, stats)
                        if m is None:
                            continue
                        ix, iy = _cell_ij_from_geom(part, 400.0)
                        mark_buckets[(kind, mat, ix, iy)].append(m)
    for junc in typed_junctions or []:
        extras = list(junc.get("stop") or []) + list(junc.get("zebra") or [])
        for poly in extras:
            for part in _iter_polygons(poly):
                m = _flat_mesh(part, MARKING_Z_M + 0.005, stats)
                if m is None:
                    continue
                ix, iy = _cell_ij_from_geom(part, 400.0)
                mark_buckets[("w", "/World/Looks/MarkingWhite", ix, iy)].append(m)
    for (kind, mat, ix, iy), meshes in mark_buckets.items():
        combined = _concat_meshes(meshes)
        if combined is None:
            continue
        _emit_flat(
            stage,
            f"/World/City/Roads/Markings/{_cell_prim(ix, iy)}_{kind}",
            combined,
            mat,
            (1.0, 1.0, 1.0),
        )
        stats.markings += 1

    UsdGeom.Xform.Define(stage, "/World/City/Roads/Arrows")
    if arrows:
        pts, counts, indices, uvs = arrow_decal_quad_cm()
        proto = "/World/City/Roads/Arrows/DecalProto"
        write_mesh(
            stage,
            proto,
            pts,
            counts,
            indices,
            "/World/Looks/Arrow",
            uvs=uvs,
            display_color=(1.0, 1.0, 1.0),
            double_sided=True,
        )
        stage.GetPrimAtPath(proto).SetCustomData({"kind": "decal", "collisionEnabled": False})
        z_cm = (LAYER_Z_M["roads"] + 0.03) * CM_PER_M
        positions = [(a["xy"][0] * CM_PER_M, a["xy"][1] * CM_PER_M, z_cm) for a in arrows]
        yaws = [a["yaw_rad"] for a in arrows]
        write_point_instancer(
            stage,
            "/World/City/Roads/Arrows/I_Arrows",
            proto,
            positions,
            yaws,
            cull_custom_data=instancer_cull_custom_data(CULL_ARROW_START_M, CULL_ARROW_END_M),
        )
        inst_prim = stage.GetPrimAtPath("/World/City/Roads/Arrows/I_Arrows")
        if inst_prim and inst_prim.IsValid():
            cd = dict(inst_prim.GetCustomData() or {})
            cd.update({"kind": "decal", "collisionEnabled": False})
            inst_prim.SetCustomData(cd)
        stats.arrows = len(arrows)


def _write_buildings_layer(
    stage, building_items, stats: BuildStats, tex: dict[str, str], uv_map: dict | None = None
) -> None:
    uv_map = uv_map or {}
    UsdGeom.Xform.Define(stage, "/World/City")
    bldg_xf = UsdGeom.Xform.Define(stage, "/World/City/Buildings")
    policy = cull_policy_summary()
    # Flat keys only — nested list/dict can fail in USD customData.
    bldg_xf.GetPrim().SetCustomData(
        {
            "cull_policy_note": str(policy.get("note") or ""),
            "cull_building_m": float(policy.get("building_m") or 0.0),
            "cull_lamp_start_m": float(policy["lamp_m"][0]) if policy.get("lamp_m") else 0.0,
            "cull_lamp_end_m": float(policy["lamp_m"][1]) if policy.get("lamp_m") else 0.0,
            "cull_sign_start_m": float(policy["sign_m"][0]) if policy.get("sign_m") else 0.0,
            "cull_sign_end_m": float(policy["sign_m"][1]) if policy.get("sign_m") else 0.0,
            "cull_arrow_start_m": float(policy["arrow_m"][0]) if policy.get("arrow_m") else 0.0,
            "cull_arrow_end_m": float(policy["arrow_m"][1]) if policy.get("arrow_m") else 0.0,
        }
    )
    for band in ("low", "mid", "high", "tower"):
        write_preview_material(
            stage,
            f"/World/Looks/Facade_{band}",
            facade_display_rgb(band),
            texture_path=tex.get(f"facade_{band}"),
            roughness=0.9,
        )
        for i in range(facade_variant_count(band)):
            key = f"facade_{band}_{i}"
            write_preview_material(
                stage,
                f"/World/Looks/Facade_{band}_{i}",
                facade_display_rgb(band),
                texture_path=tex.get(key, tex.get(f"facade_{band}")),
                roughness=0.9,
            )
    write_preview_material(stage, "/World/Looks/Roof", roof_display_rgb(), texture_path=tex.get("roof"), roughness=0.88)
    for i in range(ROOF_VARIANT_COUNT):
        write_preview_material(
            stage,
            f"/World/Looks/Roof_{i}",
            roof_display_rgb(),
            texture_path=tex.get(f"roof_{i}", tex.get("roof")),
            roughness=0.88,
        )
    write_preview_material(stage, "/World/Looks/Building", (0.76, 0.72, 0.66), texture_path=tex.get("facade_mid"))

    lod0 = LOD_LEVELS[0]
    z_bldg = LAYER_Z_M["buildings"]

    extruded: dict[int, object] = {}
    variants: dict[int, int] = {}
    print(f"USD extrude {len(building_items)} buildings individually ...", flush=True)
    for n, it in enumerate(building_items, start=1):
        band = facade_band(it["height_m"])
        way = it.get("way")
        osm_id = int(getattr(way, "osm_id", n) or n)
        tags = dict(getattr(way, "tags", None) or {})
        var = facade_variant(osm_id, band, tags)
        uv_mode = uv_map.get(f"facade_{band}_{var}", "tile")
        mesh = _extrude_building(
            it["footprint"],
            it["height_m"],
            z_bldg,
            stats,
            tile_floors=facade_tile_floors(band),
            uv_mode=uv_mode,
            sheet_width_m=facade_sheet_width_m(band),
        )
        if mesh is None:
            continue
        extruded[id(it)] = _payload_from_extrude(mesh, band, osm_id, tags)
        variants[id(it)] = var
        if n % 5000 == 0:
            print(f"USD extruded {n}/{len(building_items)} ...", flush=True)

    grouped0 = group_buildings_for_lod(building_items, lod0["cell_size_m"])
    print(f"USD LOD0 cells={len(grouped0)} merge by storey band and facade variant ...", flush=True)
    for (ix, iy), items in grouped0.items():
        by_key: dict = defaultdict(list)
        for it in items:
            payload = extruded.get(id(it))
            if payload is None:
                continue
            band = facade_band(it["height_m"])
            var = variants.get(id(it), 0)
            by_key[(band, var)].append(payload)
        for (band, var), parts in by_key.items():
            lod0_mesh = _concat_payloads(parts)
            if lod0_mesh is None:
                continue
            write_building_cell(
                stage,
                ix,
                iy,
                {"LOD0": lod0_mesh},
                lod0["switch_distance_m"],
                cell_size_m=lod0["cell_size_m"],
                suffix=f"{band}_{var}",
            )
            stats.buildings += len(parts)


def _concat_payloads(payloads: list):
    if not payloads:
        return None
    pts: list = []
    counts: list = []
    indices: list = []
    uvs: list = []
    walls: list[int] = []
    roofs: list[int] = []
    v_off = 0
    f_off = 0
    mat = payloads[0][4]
    color = payloads[0][5]
    for p in payloads:
        pts.extend(p[0])
        counts.extend(p[1])
        indices.extend(idx + v_off for idx in p[2])
        uvs.extend(p[3] or [])
        subsets = p[6] if len(p) > 6 and p[6] else {}
        walls.extend(f + f_off for f in subsets.get("Walls", ([], None))[0])
        roofs.extend(f + f_off for f in subsets.get("Roof", ([], None))[0])
        v_off += len(p[0])
        f_off += len(p[1])
    subsets = {"Walls": (walls, mat), "Roof": (roofs, payloads[0][6]["Roof"][1] if payloads[0][6] else mat)}
    return pts, counts, indices, uvs, mat, color, subsets


def _write_lamps_layer(stage, lamps, stats: BuildStats) -> None:
    UsdGeom.Xform.Define(stage, "/World/City")
    UsdGeom.Xform.Define(stage, "/World/City/Lamps")
    UsdGeom.Xform.Define(stage, "/World/City/Lamps/Prototypes")
    furn_rel = "../textures/furniture"
    lamp_proto = "/World/City/Lamps/Prototypes/Lamp/Geom"
    UsdGeom.Xform.Define(stage, "/World/City/Lamps/Prototypes/Lamp")
    write_preview_material(
        stage,
        "/World/City/Lamps/Prototypes/Lamp/Looks/Body",
        (0.22, 0.22, 0.24),
        texture_path=f"{furn_rel}/metal.png",
        roughness=0.45,
    )
    write_preview_material(
        stage,
        "/World/City/Lamps/Prototypes/Lamp/Looks/Head",
        (1.0, 0.84, 0.25),
        texture_path=f"{furn_rel}/lamp_head.png",
        roughness=0.3,
        emissive_rgb=(1.0, 0.75, 0.15),
    )
    lamp_pts, lamp_faces = placeholder_lamp_mesh()
    lamp_counts = [3] * len(lamp_faces)
    lamp_indices = [i for face in lamp_faces for i in face]
    write_mesh(
        stage,
        lamp_proto,
        lamp_pts,
        lamp_counts,
        lamp_indices,
        "/World/City/Lamps/Prototypes/Lamp/Looks/Body",
        display_color=(0.28, 0.28, 0.30),
        double_sided=True,
    )
    if lamps:
        positions = [(x * CM_PER_M, y * CM_PER_M, 0.0) for x, y, _yaw in lamps]
        yaws = [yaw for _x, _y, yaw in lamps]
        write_point_instancer(
            stage,
            "/World/City/Lamps/I_Lamps",
            lamp_proto,
            positions,
            yaws,
            cull_custom_data=instancer_cull_custom_data(CULL_LAMP_START_M, CULL_LAMP_END_M),
        )
        stats.lamps = len(lamps)


def _write_signs_layer(stage, signs, stats: BuildStats, textures_dir: Path) -> None:
    UsdGeom.Xform.Define(stage, "/World/City")
    UsdGeom.Xform.Define(stage, "/World/City/Signs")
    UsdGeom.Xform.Define(stage, "/World/City/Signs/Prototypes")
    furn_rel = "../textures/furniture"
    if not signs:
        return
    groups: dict[str, list] = {}
    for p in signs:
        label = sign_label(p.get("name", ""))
        if not label:
            continue
        groups.setdefault(label, []).append(p)
    ranked_names = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:MAX_SIGN_NAMES]
    sign_dir = Path(textures_dir) / "furniture" / "signs"
    sign_count = 0
    for i, (label, items) in enumerate(ranked_names):
        write_sign_board_png(sign_dir / f"sign_{i:03d}.png", text=label)
        proto_xf = f"/World/City/Signs/Prototypes/Sign_{i}"
        _embed_multipart_proto(
            stage,
            proto_xf,
            placeholder_sign_parts(),
            furn_rel,
            board_texture=f"{furn_rel}/signs/sign_{i:03d}.png",
        )
        positions = [(p["xy"][0] * CM_PER_M, p["xy"][1] * CM_PER_M, 0.0) for p in items]
        yaws = [p["yaw_rad"] for p in items]
        write_point_instancer(
            stage,
            f"/World/City/Signs/I_Signs_{i}",
            proto_xf,
            positions,
            yaws,
            cull_custom_data=instancer_cull_custom_data(CULL_SIGN_START_M, CULL_SIGN_END_M),
        )
        sign_count += len(items)
    stats.signs = sign_count


def _embed_multipart_proto(
    stage,
    prim_path: str,
    parts: list[dict],
    tex_dir: str,
    board_texture: Optional[str] = None,
) -> None:
    UsdGeom.Xform.Define(stage, prim_path)
    tex_for = {
        "Base": "metal.png",
        "Pole": "metal.png",
        "Collar": "metal.png",
        "Arm": "metal.png",
        "Head": "lamp_head.png",
        "Glass": "lamp_head.png",
        "Post": "metal.png",
        "Board": "sign_board.png",
        "Cap": "metal.png",
        "Trunk": "bark.png",
        "Crown": "foliage.png",
    }
    emissive = {"Head": (1.0, 0.75, 0.15), "Glass": (1.0, 0.85, 0.35)}
    for part in parts:
        name = part["name"]
        mat_path = f"{prim_path}/Looks/{name}"
        tex_name = tex_for.get(name, "metal.png")
        texture_path = board_texture if name == "Board" and board_texture else f"{tex_dir}/{tex_name}"
        write_preview_material(
            stage,
            mat_path,
            part.get("display_color") or (0.5, 0.5, 0.5),
            texture_path=texture_path,
            roughness=0.35 if name in emissive else 0.8,
            emissive_rgb=emissive.get(name),
            wrap="clamp" if name == "Board" else "repeat",
        )
        write_placeholder_prototype(
            stage,
            f"{prim_path}/{name}",
            part["verts"],
            part["faces"],
            material_path=mat_path,
            display_color=part.get("display_color"),
            uvs=part.get("uvs"),
            double_sided=bool(part.get("double_sided", name != "Board")),
        )


if __name__ == "__main__":
    sys.exit(main())
