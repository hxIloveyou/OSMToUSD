"""Archive previous scene output before a regenerate run."""
# 中文说明：开跑前备份已有 output/ 为日期 zip（排除旧 zip）。

from __future__ import annotations

import fnmatch
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from cityusd.pipeline.schema import PipelineConfig
from cityusd.scene_layout import SCENE_DATA_DIRNAME

LogFn = Callable[[str], None]


def id_prefix_from_pattern(pattern: str) -> str:
    if "{timestamp}" in pattern:
        return pattern.split("{timestamp}")[0]
    if "{" in pattern:
        return pattern.split("{", 1)[0]
    stem = pattern.rstrip("_")
    return f"{stem}_" if stem else ""


def zip_package_dir(
    source_dir: Path,
    zip_path: Path,
    *,
    exclude: Optional[list[str]] = None,
    arc_root_name: Optional[str] = None,
) -> int:
    """Zip package folder; archive paths are `<dirname>/...` inside the zip."""
    exclude = list(exclude or [])
    root_name = arc_root_name or source_dir.name
    count = 0
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(source_dir).as_posix()
            if any(
                fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat) for pat in exclude
            ):
                continue
            arc = f"{root_name}/{rel}"
            zf.write(path, arc)
            count += 1
    return count


def backup_package(
    package_dir: Path,
    backups_dir: Path,
    *,
    log: LogFn,
    suffix: str = "",
    exclude: Optional[list[str]] = None,
    zip_name: Optional[str] = None,
) -> Path | None:
    """功能：把目录打成备份 zip。"""
    if not package_dir.is_dir() or not any(package_dir.iterdir()):
        return None
    name = zip_name or f"{package_dir.name}{suffix}.zip"
    zip_path = backups_dir / name
    if zip_path.is_file():
        log(f"[backup] skip {package_dir.name} (exists: {zip_path.name})")
        return None
    n = zip_package_dir(package_dir, zip_path, exclude=exclude)
    log(f"[backup] archived {package_dir.name} → {zip_path.name} ({n} files)")
    return zip_path


def _sibling_scan_root(cfg: PipelineConfig) -> Path:
    """Where sibling packages live: SceneData/ or legacy ScenePackages/."""
    od = Path(cfg.output_dir)
    if od.name == "output" and od.parent.parent.name == SCENE_DATA_DIRNAME:
        return od.parent.parent
    return od


def _output_has_content(output_dir: Path) -> bool:
    if not output_dir.is_dir():
        return False
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".zip":
            continue
        if path.name == ".gitkeep":
            continue
        return True
    return False


def backup_output_before_run(cfg: PipelineConfig, log: LogFn) -> Path | None:
    """Zip current scene output/ (excluding *.zip) with a date stamp before overwrite.

功能：开跑前备份当前 output/。
"""
    rt = cfg.runtime
    if not bool(rt.get("backup_output_before_run", False)):
        return None

    output_dir = Path(cfg.output_dir)
    if not _output_has_content(output_dir):
        log("[backup] skip — no previous output to archive")
        return None

    backups_dir = cfg.scene_root() / str(rt.get("backup_dir", "backups"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{cfg.scene_id}_output_{stamp}.zip"
    zip_path = backups_dir / zip_name
    # Collision within the same second: append counter.
    n = 1
    while zip_path.is_file():
        zip_name = f"{cfg.scene_id}_output_{stamp}_{n}.zip"
        zip_path = backups_dir / zip_name
        n += 1

    exclude = list(rt.get("backup_exclude") or ["**/*.zip", "*.zip"])
    count = zip_package_dir(
        output_dir,
        zip_path,
        exclude=exclude,
        arc_root_name="output",
    )
    if count <= 0:
        if zip_path.is_file():
            zip_path.unlink()
        log("[backup] skip — output had no archivable files")
        return None
    log(f"[backup] previous output → backups/{zip_name} ({count} files, *.zip excluded)")
    return zip_path


def backup_previous_packages(cfg: PipelineConfig, log: LogFn) -> list[Path]:
    """Zip other packages with the same id prefix (e.g. taibei_ue_*), excluding current scene_id.

功能：备份同级旧 Scene Package（旧布局）。
"""
    rt = cfg.runtime
    if not bool(rt.get("backup_previous_packages", False)):
        return []

    scan_root = _sibling_scan_root(cfg)
    backups_dir = scan_root / str(rt.get("backup_dir", "backups"))
    prefix = id_prefix_from_pattern(cfg.scene_id_pattern)
    current = cfg.scene_id
    archived: list[Path] = []

    if not scan_root.is_dir():
        return archived

    for entry in sorted(scan_root.iterdir()):
        if not entry.is_dir() or entry.name == current:
            continue
        if entry.name == "backups":
            continue
        if prefix and not entry.name.startswith(prefix):
            continue
        hit = backup_package(entry, backups_dir, log=log, exclude=["**/*.zip", "*.zip"])
        if hit is not None:
            archived.append(hit)
    return archived


def prepare_release_run(cfg: PipelineConfig, log: LogFn) -> list[Path]:
    """Backup previous output (dated) and optional sibling packages before writing."""
    archived: list[Path] = []
    hit = backup_output_before_run(cfg, log)
    if hit is not None:
        archived.append(hit)
    archived.extend(backup_previous_packages(cfg, log))
    if bool(cfg.runtime.get("backup_self_if_exists", False)):
        # Legacy flag: also zip whole scene_root (still exclude nested zips).
        scan_root = _sibling_scan_root(cfg)
        backups_dir = scan_root / str(cfg.runtime.get("backup_dir", "backups"))
        target = cfg.scene_root() if Path(cfg.output_dir).name == "output" else cfg.package_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        hit2 = backup_package(
            target,
            backups_dir,
            log=log,
            zip_name=f"{target.name}_before_rerun_{stamp}.zip",
            exclude=["**/*.zip", "*.zip"],
        )
        if hit2 is not None:
            archived.append(hit2)
    return archived
