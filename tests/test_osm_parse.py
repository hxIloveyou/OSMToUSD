from pathlib import Path

import pytest

from cityusd.osm_parse import parse_osm

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.osm"


def _assert_tiny_counts(data) -> None:
    buildings = [w for w in data.ways if "building" in w.tags]
    roads = [w for w in data.ways if w.tags.get("highway")]
    trees = [n for n in data.nodes if n.tags.get("natural") == "tree"]
    assert len(buildings) == 1 and buildings[0].closed
    assert len(roads) == 1 and roads[0].tags["name"] == "测试路"
    assert len(trees) == 1


def test_parse_tiny_counts():
    data = parse_osm(FIXTURE)
    _assert_tiny_counts(data)
    assert data.origin.epsg == 32650  # lon 119 → zone 50


def _write_tiny_pbf(path: Path) -> None:
    import osmium
    from osmium.osm import mutable

    writer = osmium.SimpleWriter(str(path))
    nodes = [
        (1, 36.0000, 119.0000, {}),
        (2, 36.0000, 119.0008, {}),
        (3, 36.0006, 119.0008, {}),
        (4, 36.0006, 119.0000, {}),
        (5, 36.0002, 119.0000, {}),
        (6, 36.0002, 119.0008, {}),
        (7, 36.0007, 119.0002, {}),
        (8, 36.0009, 119.0002, {}),
        (9, 36.0009, 119.0005, {}),
        (10, 36.0007, 119.0005, {}),
        (40, 36.0003, 119.0004, {"natural": "tree"}),
    ]
    for nid, lat, lon, tags in nodes:
        writer.add_node(mutable.Node(id=nid, location=(lon, lat), tags=tags))
    writer.add_way(
        mutable.Way(
            id=10,
            nodes=[1, 2, 3, 4, 1],
            tags={"building": "yes", "building:levels": "3"},
        )
    )
    writer.add_way(
        mutable.Way(
            id=20,
            nodes=[5, 6],
            tags={"highway": "residential", "name": "测试路"},
        )
    )
    writer.add_way(
        mutable.Way(
            id=30,
            nodes=[7, 8, 9, 10, 7],
            tags={"natural": "water"},
        )
    )
    writer.close()


def test_parse_tiny_pbf_counts(tmp_path: Path):
    pbf = tmp_path / "tiny.osm.pbf"
    _write_tiny_pbf(pbf)
    data = parse_osm(pbf)
    _assert_tiny_counts(data)
    assert data.origin.epsg == 32650


def test_parse_empty_osm_raises(tmp_path: Path):
    empty = tmp_path / "empty.osm"
    empty.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6"/>\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no nodes"):
        parse_osm(empty)
