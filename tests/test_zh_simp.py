from cityusd.zh_simp import to_simplified


def test_taiwan_road_names_to_simplified():
    assert to_simplified("復興南路") == "复兴南路"
    assert to_simplified("臺北市信義區") == "台北市信义区"
    assert to_simplified("中山北路") == "中山北路"
    assert to_simplified("") == ""
