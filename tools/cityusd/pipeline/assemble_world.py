from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from cityusd.package import WORLD_SUBLAYERS, build_package_meta, write_meta, write_world
from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref
from cityusd.pipeline.terrain import load_extent_context
from cityusd.usd_write import write_environment_layer, write_terrain_layer

LogFn = Callable[[str], None]

_CITY_STEMS = (
    "city_water",
    "city_vegetation",
    "city_roads",
    "city_buildings",
    "city_lamps",
    "city_signs",
)


def _resolve_input(cfg: PipelineConfig, key: str) -> Path | None:
    block = cfg.inputs.get(key) or {}
    raw = block.get("path")
    if not raw:
        return None
    p = Path(str(raw)).expanduser()
    if not p.is_absolute():
        cand = (cfg.project_root / p).resolve()
        if cand.is_file():
            return cand
    return p if p.is_file() else None


def _load_city_layers(package_dir: Path) -> dict[str, str]:
    stats_path = package_dir / "layers" / "city_build_stats.json"
    if stats_path.is_file():
        try:
            payload = json.loads(stats_path.read_text(encoding="utf-8"))
            layers = payload.get("city_layers") or {}
            if layers:
                return {str(k): str(v) for k, v in layers.items()}
        except json.JSONDecodeError:
            pass

    found: dict[str, str] = {}
    layers_dir = package_dir / "layers"
    for stem in _CITY_STEMS:
        for suffix in (".usdc", ".usda"):
            path = layers_dir / f"{stem}{suffix}"
            if path.is_file():
                found[stem] = f"./layers/{path.name}"
                break
    return found


def _resolve_sublayers(
    package_dir: Path,
    template: list[str],
    city_layers: dict[str, str],
    *,
    skip_missing: bool,
    log: LogFn,
) -> list[str]:
    resolved: list[str] = []
    for item in template:
        rel = item
        for stem, actual in city_layers.items():
            rel = rel.replace(f"./layers/{stem}.usdc", actual)
            rel = rel.replace(f"./layers/{stem}.usda", actual)
        path = package_dir / rel.removeprefix("./")
        if path.is_file():
            resolved.append(rel)
        elif skip_missing:
            log(f"[assemble_world] skip missing sublayer: {rel}")
        else:
            raise FileNotFoundError(f"assemble_world missing sublayer: {rel}")
    return resolved


def _ensure_environment(package_dir: Path) -> str:
    rel = "./layers/environment.usda"
    path = package_dir / "layers" / "environment.usda"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_environment_layer(path)
    return rel


def _ensure_terrain_layer(package_dir: Path, log: LogFn) -> str | None:
    terrain_usda = package_dir / "layers" / "terrain.usda"
    if terrain_usda.is_file():
        return "./layers/terrain.usda"

    align_path = package_dir / "terrain" / "alignment.json"
    hm_png = package_dir / "terrain" / "heightmap_ue.png"
    if not hm_png.is_file() and not align_path.is_file():
        return None

    heightmap_rel = "./terrain/heightmap_ue.png" if hm_png.is_file() else None
    ortho_rel = "./terrain/ortho_ue.png" if (package_dir / "terrain" / "ortho_ue.png").is_file() else None

    terrain_usda.parent.mkdir(parents=True, exist_ok=True)
    write_terrain_layer(terrain_usda, heightmap_rel, ortho_rel, None)
    log("[assemble_world] wrote layers/terrain.usda")
    return "./layers/terrain.usda"


def _write_sources_manifest(cfg: PipelineConfig, package_dir: Path) -> None:
    path = package_dir / "sources_manifest.json"
    sources: dict = {}
    if path.is_file():
        try:
            sources = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sources = {}

    osm = _resolve_input(cfg, "osm")
    if osm is not None:
        sources.setdefault("osm", str(osm))
    dem = _resolve_input(cfg, "dem")
    if dem is not None:
        sources.setdefault("dem", str(dem))
    ortho = _resolve_input(cfg, "ortho")
    if ortho is not None:
        sources.setdefault("imagery", str(ortho))

    sources["extent"] = "./extent.json"
    catalog_manifest = package_dir / "catalog" / "index" / "shard_manifest.json"
    if catalog_manifest.is_file():
        sources["catalog"] = "./catalog/index/shard_manifest.json"

    path.write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_assets_used(package_dir: Path) -> None:
    items: list[dict] = []
    proto_dir = package_dir / "models" / "prototypes"
    if proto_dir.is_dir():
        for name in ("tree.usda", "lamp.usda", "sign.usda"):
            if (proto_dir / name).is_file():
                items.append(
                    {
                        "name": name.replace(".usda", "_placeholder"),
                        "source": "generated",
                        "path": f"./models/prototypes/{name}",
                    }
                )

    tex_dir = package_dir / "textures"
    if tex_dir.is_dir():
        for path in sorted(tex_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                items.append(
                    {
                        "name": path.stem,
                        "source": "generated",
                        "path": "./" + path.relative_to(package_dir).as_posix(),
                    }
                )

    if items:
        (package_dir / "assets_used.json").write_text(
            json.dumps({"items": items}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def run_assemble_world(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    step = cfg.step("assemble_world")
    if step is None:
        raise RuntimeError("assemble_world step missing from pipeline")

    extent_payload, origin, extent = load_extent_context(package_dir)
    step_cfg = load_step_config_ref(cfg, step, package_dir)

    world_pattern = str(step_cfg.get("world_file", "World_{scene_id}.usda"))
    world_name = world_pattern.replace("{scene_id}", cfg.scene_id)
    world_rel = world_name
    world_path = package_dir / world_name

    template = list(step_cfg.get("sublayers") or WORLD_SUBLAYERS)
    skip_missing = bool(step_cfg.get("skip_missing_sublayers", True))

    _ensure_environment(package_dir)
    _ensure_terrain_layer(package_dir, log)

    city_layers = _load_city_layers(package_dir)
    if not city_layers:
        raise RuntimeError("assemble_world: no city layers found — run osm_city_usd first")

    sublayers = _resolve_sublayers(
        package_dir,
        template,
        city_layers,
        skip_missing=skip_missing,
        log=log,
    )
    if not sublayers:
        raise RuntimeError("assemble_world: no sublayers resolved")

    log(f"[assemble_world] World subLayers={len(sublayers)}")
    write_world(world_path, cfg.scene_id, sublayers)

    crs = {
        "epsg": origin.epsg,
        "origin_wgs84": {
            "lon": origin.lon,
            "lat": origin.lat,
            "height_m": origin.height_m,
        },
        "extent_m": extent.to_json(),
        "range_source": str(extent_payload.get("resolution", {}).get("osm_vs_terrain", "pipeline_extent")),
    }
    meta = build_package_meta(cfg.scene_id, crs=crs)
    meta["layers"].update(city_layers)
    meta["title"] = cfg.scene_title
    meta["layout"] = cfg.output_layout
    meta["pipeline_schema"] = cfg.schema_version

    if (package_dir / "nav2" / "connected" / "map.pgm").is_file():
        meta["nav"] = {
            "map_pgm": "./nav2/connected/map.pgm",
            "map_yaml": "./nav2/connected/map_local.yaml",
            "map_yaml_utm": "./nav2/connected/map.yaml",
            "valhalla_origin": "./nav2/connected/valhalla_origin.yaml",
            "cost_pgm": "./nav2/connected/cost.pgm",
        }
    if (package_dir / "nav2" / "nature" / "nature_bmp.yaml").is_file():
        meta.setdefault("nav2", {})["nature"] = "./nav2/nature/nature_bmp.yaml"

    catalog_manifest = package_dir / "catalog" / "index" / "shard_manifest.json"
    if catalog_manifest.is_file():
        meta["catalog"] = {
            "shard_manifest": "./catalog/index/shard_manifest.json",
            "compose_into_world": False,
        }

    stats_path = package_dir / "layers" / "city_build_stats.json"
    if stats_path.is_file():
        try:
            meta["city_build"] = json.loads(stats_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    write_meta(package_dir / "meta.json", meta)
    _write_sources_manifest(cfg, package_dir)
    _write_assets_used(package_dir)

    written = [
        world_rel,
        "meta.json",
        "sources_manifest.json",
        "layers/environment.usda",
    ]
    if (package_dir / "layers" / "terrain.usda").is_file():
        written.append("layers/terrain.usda")
    if (package_dir / "assets_used.json").is_file():
        written.append("assets_used.json")

    snap = package_dir / "configs" / "assemble_world.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append("configs/assemble_world.resolved.json")

    log(f"[assemble_world] ok → {world_name}")
    return written
