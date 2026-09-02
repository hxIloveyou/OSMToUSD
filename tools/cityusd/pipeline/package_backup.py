"""Archive sibling Scene Packages before a dated release run."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Callable

from cityusd.pipeline.schema import PipelineConfig

LogFn = Callable[[str], None]


def id_prefix_from_pattern(pattern: str) -> str:
    if "{timestamp}" in pattern:
        return pattern.split("{timestamp}")[0]
    if "{" in pattern:
        return pattern.split("{", 1)[0]
    stem = pattern.rstrip("_")
    return f"{stem}_" if stem else ""


def zip_package_dir(source_dir: Path, zip_path: Path) -> int:
    """Zip package folder; archive paths are `<dirname>/...` inside the zip."""
    count = 0
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            arc = f"{source_dir.name}/{path.relative_to(source_dir).as_posix()}"
            zf.write(path, arc)
            count += 1
    return count


def backup_package(
    package_dir: Path,
    backups_dir: Path,
    *,
    log: LogFn,
    suffix: str = "",
) -> Path | None:
    if not package_dir.is_dir() or not any(package_dir.iterdir()):
        return None
    name = f"{package_dir.name}{suffix}.zip"
    zip_path = backups_dir / name
    if zip_path.is_file():
        log(f"[backup] skip {package_dir.name} (exists: {zip_path.relative_to(backups_dir.parent)})")
        return None
    n = zip_package_dir(package_dir, zip_path)
    log(f"[backup] archived {package_dir.name} → {zip_path.name} ({n} files)")
    return zip_path


def backup_previous_packages(cfg: PipelineConfig, log: LogFn) -> list[Path]:
    """Zip other packages with the same id prefix (e.g. taibei_ue_*), excluding current scene_id."""
    rt = cfg.runtime
    if not bool(rt.get("backup_previous_packages", False)):
        return []

    backups_dir = cfg.output_dir / str(rt.get("backup_dir", "backups"))
    prefix = id_prefix_from_pattern(cfg.scene_id_pattern)
    current = cfg.scene_id
    archived: list[Path] = []

    if not cfg.output_dir.is_dir():
        return archived

    for entry in sorted(cfg.output_dir.iterdir()):
        if not entry.is_dir() or entry.name == current:
            continue
        if entry.name == "backups":
            continue
        if prefix and not entry.name.startswith(prefix):
            continue
        hit = backup_package(entry, backups_dir, log=log)
        if hit is not None:
            archived.append(hit)
    return archived


def prepare_release_run(cfg: PipelineConfig, log: LogFn) -> list[Path]:
    """Backup siblings and optionally the target package before writing."""
    archived = backup_previous_packages(cfg, log)
    if bool(cfg.runtime.get("backup_self_if_exists", False)):
        backups_dir = cfg.output_dir / str(cfg.runtime.get("backup_dir", "backups"))
        hit = backup_package(
            cfg.package_dir(),
            backups_dir,
            log=log,
            suffix="_before_rerun",
        )
        if hit is not None:
            archived.append(hit)
    return archived
