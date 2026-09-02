"""Tests for AssetLibrary inbox path resolution."""

from __future__ import annotations

from pathlib import Path

from cityusd.inbox_assets import INBOX_REL
from cityusd.inbox_bind import resolve_asset_library_root


def test_resolve_staged_assets_root(tmp_path: Path):
    root = tmp_path / "assets"
    inbox = root / INBOX_REL / "facades" / "tileable" / "midrise"
    inbox.mkdir(parents=True)
    (inbox / "a.jpg").write_bytes(b"x")
    assert resolve_asset_library_root(root, tmp_path) == root


def test_resolve_nested_asset_library(tmp_path: Path):
    root = tmp_path / "assets" / "AssetLibrary"
    inbox = root / INBOX_REL / "facades" / "sheets" / "shopfront"
    inbox.mkdir(parents=True)
    (inbox / "b.jpg").write_bytes(b"x")
    assert resolve_asset_library_root(tmp_path / "assets", tmp_path) == root
