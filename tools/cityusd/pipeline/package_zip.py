# 中文说明：package_zip 步骤：将 scene output/（USD+CostMap）打成 zip。
from __future__ import annotations

import fnmatch
import json
import zipfile
from pathlib import Path
from typing import Callable

from cityusd.pipeline.schema import PipelineConfig, load_step_config_ref

LogFn = Callable[[str], None]

# 默认排除：备份、调试、以及任何 zip（防止把正在写的 zip 再打进自身 → 撑爆磁盘）
_DEFAULT_EXCLUDE = ["backups/**", "debug/**", "**/*.pending.json", "**/*.zip", "*.zip"]


def _should_exclude(rel_posix: str, patterns: list[str]) -> bool:
    name = Path(rel_posix).name
    for pat in patterns:
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(name, pat):
            return True
        # fnmatch 的 ** 不是递归通配；补一层「任意前缀/*.zip」
        if pat.endswith("/**") and ("/" + rel_posix).endswith("/" + pat[:-3].rstrip("/")):
            return True
    return False


def run_package_zip(cfg: PipelineConfig, package_dir: Path, log: LogFn) -> list[str]:
    """功能：打包 output/ 为 zip。"""
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
    archive_root = archive_root.resolve()

    out_spec = step_cfg.get("output_dir")
    if out_spec:
        zip_path = Path(str(out_spec)).expanduser()
        if not zip_path.is_absolute():
            zip_path = (cfg.project_root / zip_path).resolve()
        if zip_path.suffix.lower() != ".zip":
            zip_path = zip_path / zip_name
    else:
        zip_path = cfg.scene_root() / zip_name
    zip_path = zip_path.resolve()

    # 测试里 output_dir 常等于 scene_root：zip 若落在归档根内，必须排除自身，否则会自膨胀。
    if zip_path.parent == archive_root or archive_root in zip_path.parents:
        # 仍允许写在 scene_root；下面遍历时跳过 zip_path
        pass

    exclude = list(step_cfg.get("exclude") or _DEFAULT_EXCLUDE)
    for pat in ("*.zip", "**/*.zip"):
        if pat not in exclude:
            exclude.append(pat)

    compression_name = str(step_cfg.get("compression", "deflated")).lower()
    compression = zipfile.ZIP_DEFLATED if compression_name != "stored" else zipfile.ZIP_STORED

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.is_file():
        zip_path.unlink()

    count = 0
    total_bytes = 0
    with zipfile.ZipFile(zip_path, "w", compression=compression) as zf:
        for path in sorted(archive_root.rglob("*")):
            if not path.is_file():
                continue
            try:
                if path.resolve() == zip_path:
                    continue
            except OSError:
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
