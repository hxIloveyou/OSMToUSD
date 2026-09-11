"""Download CC0 facade/roof candidates into AssetLibrary inbox. Does not rebuild USD."""
# 中文说明：下载或整理 AssetLibrary inbox 材质候选；--rehome 仅重排已有文件。

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cityusd.inbox_assets import dest_path, ensure_inbox, rehome_inbox, write_manifest


def main(argv: list[str] | None = None) -> int:
    """Download or rehome inbox assets and write manifest.

    功能：下载或重排 inbox 资产并写 manifest。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tools" / "assets" / "AssetLibrary",
        help="AssetLibrary root (workspace copy)",
    )
    parser.add_argument(
        "--rehome",
        action="store_true",
        help="Only regroup existing files into browse folders; do not download",
    )
    args = parser.parse_args(argv)
    library = args.library.resolve()
    print(f"inbox library: {library}", flush=True)
    if args.rehome:
        result = rehome_inbox(library)
        kept = [
            a
            for a in result["assets"]
            if dest_path(library, a).is_file() and dest_path(library, a).stat().st_size > 1000
        ]
        write_manifest(library, kept)
        print(
            f"rehome moved={result['moved']} kept={len(kept)} missing={len(result['missing'])}",
            flush=True,
        )
        if result["missing"]:
            print("missing: " + ", ".join(result["missing"][:20]), flush=True)
        return 0 if result["listed"] else 1
    result = ensure_inbox(library)
    print(
        f"inbox done listed={result['listed']} present={result['ok']} failed={len(result['fail'])}",
        flush=True,
    )
    if result["fail"]:
        print("failed: " + ", ".join(result["fail"]), flush=True)
    print(f"manifest: {result['manifest']}", flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
