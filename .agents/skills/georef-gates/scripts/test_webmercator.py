# uvx --with numpy --with pyproj --with pytest pytest scripts/test_webmercator.py
import numpy as np
import pytest
from pyproj import Transformer

import webmercator as wm


def test_tokyo_tile_index():
    # Imperial Palace area, tile fetched from tile.yuiseki.net on 2026-11-03
    x, y = wm.lonlat_to_global_px(139.7528, 35.6852, 14)
    assert int(x // 256) == 14552
    assert int(y // 256) == 6451


@pytest.mark.parametrize("lat", [-80.0, -35.0, 0.0, 35.6852, 64.1, 84.9])
def test_mercator_metres_match_pyproj(lat):
    lon = 139.7528 if lat > 0 else -70.3
    to3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    ex, ey = to3857.transform(lon, lat)
    for z in (0, 10, 17):
        gx, gy = wm.lonlat_to_global_px(lon, lat, z)
        mx, my = wm.global_px_to_mercator(gx, gy, z)
        assert mx == pytest.approx(ex, abs=1e-6)
        assert my == pytest.approx(ey, abs=1e-6)


def test_round_trip_high_latitude():
    lon = np.array([-179.9, -20.0, 10.0, 179.9])
    lat = np.array([84.0, 70.0, -60.0, 1.0])
    gx, gy = wm.lonlat_to_global_px(lon, lat, 15)
    lon2, lat2 = wm.global_px_to_lonlat(gx, gy, 15)
    np.testing.assert_allclose(lon2, lon, atol=1e-9)
    np.testing.assert_allclose(lat2, lat, atol=1e-9)
    mx, my = wm.global_px_to_mercator(gx, gy, 15)
    gx2, gy2 = wm.mercator_to_global_px(mx, my, 15)
    np.testing.assert_allclose(gx2, gx, atol=1e-6)
    np.testing.assert_allclose(gy2, gy, atol=1e-6)


def test_y_grows_southwards_and_lon_is_not_swapped():
    _, y_north = wm.lonlat_to_global_px(0.0, 60.0, 5)
    _, y_south = wm.lonlat_to_global_px(0.0, -60.0, 5)
    assert y_north < y_south
    x_west, _ = wm.lonlat_to_global_px(-120.0, 60.0, 5)
    x_east, _ = wm.lonlat_to_global_px(120.0, 60.0, 5)
    assert x_west < x_east


def test_latitude_outside_mercator_is_an_error():
    with pytest.raises(ValueError):
        wm.lonlat_to_global_px(0.0, 89.0, 3)
    with pytest.raises(ValueError):
        wm.lonlat_to_global_px(181.0, 0.0, 3)


def test_ground_resolution_at_tokyo_z14():
    # 2 pi R / (256 2^14) times cos(lat)
    r = wm.ground_resolution(35.6852, 14)
    assert r == pytest.approx(9.554628535647032 * np.cos(np.radians(35.6852)), rel=1e-12)
