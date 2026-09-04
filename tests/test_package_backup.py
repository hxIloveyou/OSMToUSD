"""Tests for release backup + dated scene ids."""

from __future__ import annotations

import zipfile
from pathlib import Path

from cityusd.pipeline.package_backup import (
    backup_output_before_run,
    backup_previous_packages,
    id_prefix_from_pattern,
    zip_package_dir,
)
from cityusd.pipeline.schema import PipelineConfig, _ensure_scene_id


def _cfg(tmp_path: Path, scene_id: str, **runtime) -> PipelineConfig:
    rt = {
        "backup_previous_packages": True,
        "backup_dir": "backups",
    }
    rt.update(runtime)
    return PipelineConfig(
        schema_version="0.3",
        scene_id=scene_id,
        scene_title="t",
        scene_id_pattern="taibei_ue_{timestamp}",
        frame={},
        inputs={},
        output_dir=tmp_path,
        output_layout="cityusd_v1",
        steps=[],
        runtime=rt,
        raw={},
        source_path=tmp_path / "p.yaml",
        project_root=tmp_path,
    )


def test_id_prefix_from_pattern():
    assert id_prefix_from_pattern("taibei_ue_{timestamp}") == "taibei_ue_"


def test_ensure_scene_id_date_stamp():
    sid = _ensure_scene_id({"id_pattern": "taibei_ue_{timestamp}"}, {"scene_id_stamp": "date"})
    assert sid.startswith("taibei_ue_")
    assert len(sid.split("_")[-1]) == 8


def test_backup_previous_packages(tmp_path: Path):
    old = tmp_path / "taibei_ue_20260831"
    old.mkdir()
    (old / "meta.json").write_text("{}", encoding="utf-8")
    new_id = "taibei_ue_20260902"
    cfg = _cfg(tmp_path, new_id)

    logs: list[str] = []
    archived = backup_previous_packages(cfg, logs.append)

    assert len(archived) == 1
    assert archived[0].name == "taibei_ue_20260831.zip"
    with zipfile.ZipFile(archived[0]) as zf:
        assert "taibei_ue_20260831/meta.json" in zf.namelist()

    archived2 = backup_previous_packages(cfg, logs.append)
    assert archived2 == []


def test_zip_package_dir(tmp_path: Path):
    pkg = tmp_path / "demo_pkg"
    pkg.mkdir()
    (pkg / "a.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "demo_pkg.zip"
    n = zip_package_dir(pkg, out)
    assert n == 1
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["demo_pkg/a.txt"]


def test_backup_output_before_run_excludes_zip(tmp_path: Path):
    scene = tmp_path / "SceneData" / "demo"
    out = scene / "output"
    usd = out / "demo-USD"
    usd.mkdir(parents=True)
    (usd / "meta.json").write_text("{}", encoding="utf-8")
    (out / "stale.zip").write_bytes(b"PK\x03\x04nested")

    cfg = _cfg(
        out,
        "demo",
        backup_previous_packages=False,
        backup_output_before_run=True,
        backup_dir="backups",
        backup_exclude=["**/*.zip", "*.zip"],
    )
    assert cfg.scene_root() == scene

    logs: list[str] = []
    hit = backup_output_before_run(cfg, logs.append)
    assert hit is not None
    assert hit.name.startswith("demo_output_")
    assert hit.parent == scene / "backups"
    with zipfile.ZipFile(hit) as zf:
        names = zf.namelist()
    assert "output/demo-USD/meta.json" in names
    assert not any(n.endswith(".zip") for n in names)


def test_backup_output_skips_when_empty(tmp_path: Path):
    scene = tmp_path / "SceneData" / "empty"
    out = scene / "output"
    (out / "empty-CostMap" / "3D").mkdir(parents=True)
    (out / "empty-CostMap" / "3D" / ".gitkeep").write_text("", encoding="utf-8")
    cfg = _cfg(out, "empty", backup_previous_packages=False, backup_output_before_run=True)
    logs: list[str] = []
    assert backup_output_before_run(cfg, logs.append) is None
