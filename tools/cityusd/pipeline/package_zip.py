from __future__ import annotations

import fnmatch
import json
import zipfile
from pathlib import Path
from typing import Callable

from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref

LogFn = Callable[[str], None]


def _should_exclude(rel_posix: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(Path(rel_posix).name, pat):
            return True
    return False


def run_package_zip(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    step = cfg.step("package_zip")
    if step is None:
        raise RuntimeError("package_zip step missing from pipeline")

    step_cfg = load_step_config_ref(cfg, step, package_dir)
    output_pattern = str(step_cfg.get("output", "{scene_id}.zip"))
    zip_name = output_pattern.replace("{scene_id}", cfg.scene_id)

    # Zip USD + CostMap together from the scene output/ folder.
    archive_root = Path(cfg.output_dir)
    if not archive_root.is_dir():
        archive_root = package_dir.parent if package_dir.parent.is_dir() else package_dir

    out_spec = step_cfg.get("output_dir")
    if out_spec:
        zip_path = Path(str(out_spec)).expanduser()
        if not zip_path.is_absolute():
            zip_path = (cfg.project_root / zip_path).resolve()
        if zip_path.suffix.lower() != ".zip":
            zip_path = zip_path / zip_name
    else:
        zip_path = cfg.scene_root() / zip_name

    exclude = list(step_cfg.get("exclude") or ["backups/**", "**/*.pending.json", "**/*.zip"])
    compression_name = str(step_cfg.get("compression", "deflated")).lower()
    compression = zipfile.ZIP_DEFLATED if compression_name != "stored" else zipfile.ZIP_STORED

    if zip_path.is_file():
        zip_path.unlink()

    count = 0
    total_bytes = 0
    with zipfile.ZipFile(zip_path, "w", compression=compression) as zf:
        for path in sorted(archive_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(archive_root).as_posix()
            if _should_exclude(rel, exclude):
                continue
            zf.write(path, rel)
            count += 1
            total_bytes += path.stat().st_size

    manifest_entry = {
        "path": str(zip_path),
        "files": count,
        "uncompressed_bytes": total_bytes,
        "archive_root": str(archive_root),
    }
    sidecar = package_dir / "package.zip.json"
    sidecar.write_text(json.dumps(manifest_entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    snap = package_dir / "configs" / "package_zip.resolved.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(step_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log(f"[package_zip] ok → {zip_path.name} ({count} files from {archive_root.name}/)")
    return [str(zip_path), "package.zip.json", "configs/package_zip.resolved.json"]
