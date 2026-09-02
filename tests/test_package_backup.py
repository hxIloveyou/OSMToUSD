"""Tests for release backup + dated scene ids."""

from __future__ import annotations

import zipfile
from pathlib import Path

from cityusd.pipeline.package_backup import backup_previous_packages, id_prefix_from_pattern, zip_package_dir
from cityusd.pipeline.schema import PipelineConfig, _ensure_scene_id


def _cfg(tmp_path: Path, scene_id: str) -> PipelineConfig:
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
        runtime={
            "backup_previous_packages": True,
            "backup_dir": "backups",
        },
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
