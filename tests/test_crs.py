# tests/test_crs.py
from cityusd.crs import lonlat_to_local, local_to_lonlat, make_origin, utm_epsg


def test_taipei_epsg():
    assert utm_epsg(121.53296235, 25.04756678) == 32651


def test_origin_is_zero():
    o = make_origin(121.53296235, 25.04756678)
    x, y = lonlat_to_local(o.lon, o.lat, o)
    assert abs(x) < 1e-6 and abs(y) < 1e-6


def test_roundtrip():
    o = make_origin(121.53296235, 25.04756678)
    lon, lat = 121.54, 25.05
    x, y = lonlat_to_local(lon, lat, o)
    lon2, lat2 = local_to_lonlat(x, y, o)
    assert abs(lon - lon2) < 1e-7 and abs(lat - lat2) < 1e-7
