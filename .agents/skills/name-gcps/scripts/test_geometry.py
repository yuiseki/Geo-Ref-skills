# uvx --with pytest pytest scripts/test_geometry.py
import pytest

import geometry


def test_distance_to_a_line_is_to_its_nearest_segment():
    g = geometry.Shapes(lines=[[(0, 0), (100, 0), (100, 100)]])
    assert g.distance((50, 10)) == pytest.approx(10)
    assert g.closest((50, 10)) == pytest.approx((50, 0))
    assert g.distance((110, 50)) == pytest.approx(10)


def test_the_middle_of_an_area_is_distance_zero():
    sq = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    g = geometry.Shapes(areas=[sq])
    assert g.distance((50, 50)) == 0 and g.closest((50, 50)) == (50, 50)
    r = 0.25 * (1e4 / 3.14159265) ** 0.5
    assert g.distance((150, 50)) == pytest.approx(100 - r, rel=1e-3)


def test_points_and_extent():
    g = geometry.Shapes(points=[(0, 0), (30, 40)])
    assert g.distance((30, 44)) == pytest.approx(4)
    assert g.extent() == pytest.approx(50)
    assert geometry.Shapes().empty()


def test_from_overpass_elements():
    els = [{"type": "node", "lat": 0.0, "lon": 0.0},
           {"type": "way", "geometry": [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.001}]},
           {"type": "way", "geometry": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 0.001}, {"lat": 0.001, "lon": 0.001},
                                        {"lat": 0, "lon": 0}]},
           {"type": "relation", "members": [{"type": "way", "geometry": [{"lat": 0.0, "lon": 0.0},
                                                                          {"lat": 0.001, "lon": 0.0}]}]}]
    g = geometry.Shapes.from_overpass(els, lambda lon, lat: (lon * 1e5, lat * 1e5))
    assert len(g.points) == 1 and len(g.lines) == 2 and len(g.areas) == 1
    assert g.distance((70, 30)) == 0  # inside the closed triangle (0,0)-(100,0)-(100,100)


def test_an_area_is_measured_from_near_its_middle_not_anywhere_inside():
    sq = [(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)]
    g = geometry.Shapes(areas=[sq])
    assert g.distance((500, 500)) == 0
    # the core is a disc of 0.25 x the equivalent radius (564 m for this square): about 141 m
    assert g.distance((500, 600)) == 0
    assert g.distance((500, 900)) == pytest.approx(400 - 0.25 * (1e6 / 3.14159265) ** 0.5, rel=1e-3)
    assert g.closest((500, 900))[1] == pytest.approx(500 + 0.25 * (1e6 / 3.14159265) ** 0.5, rel=1e-3)
