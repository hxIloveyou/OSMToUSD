from cityusd.furniture import (
    lamp_instances,
    placeholder_lamp_parts,
    placeholder_sign_parts,
    placeholder_tree_mesh,
    sign_label,
)
from cityusd.osm_parse import OsmWay
from cityusd.types import CM_PER_M


def test_lamp_only_primary():
    res = OsmWay(1, {"highway": "residential"}, [(0.0, 0.0), (40.0, 0.0)], False)
    pri = OsmWay(2, {"highway": "primary"}, [(0.0, 10.0), (60.0, 10.0)], False)
    assert lamp_instances([res]) == []
    assert len(lamp_instances([pri])) >= 2


def test_tree_placeholder_has_faces():
    v, f = placeholder_tree_mesh()
    assert len(v) > 8 and len(f) > 4


def test_sign_label_fallback():
    assert sign_label("") == ""
    assert sign_label("  中山北路  ") == "中山北路"
    assert sign_label("復興南路") == "复兴南路"


def test_sign_board_uv_readable_oncoming():
    board = next(p for p in placeholder_sign_parts() if p["name"] == "Board")
    oncoming = board["verts"][4:8]
    uvs = board["uvs"][4:8]
    max_y_i = max(range(4), key=lambda i: oncoming[i][1])
    min_y_i = min(range(4), key=lambda i: oncoming[i][1])
    assert uvs[max_y_i][0] < uvs[min_y_i][0]
    max_z_i = max(range(4), key=lambda i: oncoming[i][2])
    min_z_i = min(range(4), key=lambda i: oncoming[i][2])
    assert uvs[max_z_i][1] > uvs[min_z_i][1]


def test_sign_post_is_taller():
    post = next(p for p in placeholder_sign_parts() if p["name"] == "Post")
    zs = [v[2] for v in post["verts"]]
    assert max(zs) >= 4.0 * CM_PER_M


def test_sign_board_mesh_is_single_sided():
    board = next(p for p in placeholder_sign_parts() if p["name"] == "Board")
    assert board.get("double_sided") is False


def test_sign_board_faces_travel_axis():
    board = next(p for p in placeholder_sign_parts() if p["name"] == "Board")
    xs = [v[0] for v in board["verts"]]
    ys = [v[1] for v in board["verts"]]
    assert max(ys) - min(ys) > max(xs) - min(xs)
    assert max(ys) - min(ys) > 200.0


def test_lamp_has_cobra_parts():
    names = {p["name"] for p in placeholder_lamp_parts()}
    assert {"Base", "Pole", "Arm", "Head", "Glass"} <= names
    pole = next(p for p in placeholder_lamp_parts() if p["name"] == "Pole")
    assert len(pole["verts"]) > 40
    zs = [v[2] for v in pole["verts"]]
    assert 3.6 * CM_PER_M < max(zs) < 5.0 * CM_PER_M
    sign_post = next(p for p in placeholder_sign_parts() if p["name"] == "Post")
    sign_h = max(v[2] for v in sign_post["verts"])
    assert abs(max(zs) - sign_h) < 0.6 * CM_PER_M
