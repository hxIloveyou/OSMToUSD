from shapely.geometry import Polygon

from cityusd.geom import triangulate_polygon, to_mesh_cm


def test_unit_square_two_tris():
    verts, faces = triangulate_polygon(Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]))
    assert len(faces) >= 2
    pts, _ = to_mesh_cm(verts, faces, z_m=0.08)
    assert all(abs(p[2] - 8.0) < 1e-6 for p in pts)  # 0.08m → 8cm


def test_polygon_with_hole_triangulates():
    outer = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
    hole = [(8.0, 8.0), (8.0, 12.0), (12.0, 12.0), (12.0, 8.0)]
    verts, faces = triangulate_polygon(Polygon(outer, [hole]))
    assert len(verts) == 8
    assert len(faces) >= 8
    # hole interior is not covered by any triangle centroid inside the hole
    hx, hy = 10.0, 10.0
    for a, b, c in faces:
        x = (verts[a][0] + verts[b][0] + verts[c][0]) / 3.0
        y = (verts[a][1] + verts[b][1] + verts[c][1]) / 3.0
        assert not (8.2 < x < 11.8 and 8.2 < y < 11.8)
