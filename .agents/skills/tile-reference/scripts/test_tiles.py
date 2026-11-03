# uvx --with numpy --with pillow --with pytest pytest scripts/test_tiles.py
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import tiles


def coded_tile(tx, ty, size=256):
    """R = column in tile, G = row in tile, B encodes the tile index."""
    v, u = np.mgrid[0:size, 0:size]
    img = np.zeros((size, size, 3), np.uint8)
    img[..., 0] = u % 256
    img[..., 1] = v % 256
    img[..., 2] = (tx + 3 * ty) % 256
    return img


def fill_cache(cache, style, z, txs, tys, size=256):
    for tx in txs:
        for ty in tys:
            p = tiles.cache_path(cache, style, z, tx, ty, size)
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(coded_tile(tx, ty, size)).save(p)


def test_mosaic_places_every_pixel(tmp_path):
    fill_cache(tmp_path, "s", 10, range(100, 104), range(200, 203))
    x0, y0, x1, y1 = 100 * 256 + 37.4, 200 * 256 + 5.9, 103 * 256 + 12.0, 202 * 256 + 255.5
    img, ox, oy, stats = tiles.mosaic("s", 10, x0, y0, x1, y1, tmp_path, offline=True)
    assert (ox, oy) == (100 * 256 + 37, 200 * 256 + 5)
    assert img.shape == (202 * 256 + 256 - oy, 103 * 256 + 12 - ox, 3)
    rng = np.random.default_rng(0)
    for _ in range(500):
        j = rng.integers(0, img.shape[0])
        i = rng.integers(0, img.shape[1])
        gx, gy = ox + i, oy + j
        tx, ty = gx // 256, gy // 256
        assert tuple(img[j, i]) == (gx % 256, gy % 256, (tx + 3 * ty) % 256)
    assert stats == {"cached": 12, "fetched": 0}


def test_missing_tile_offline_is_an_error(tmp_path):
    fill_cache(tmp_path, "s", 10, [100], [200])
    with pytest.raises(FileNotFoundError):
        tiles.mosaic("s", 10, 100 * 256, 200 * 256, 101 * 256 + 10, 200 * 256 + 10, tmp_path, offline=True)


def test_wrong_tile_size_is_an_error(tmp_path):
    fill_cache(tmp_path, "s", 3, [1], [1], size=128)
    p128 = tiles.cache_path(tmp_path, "s", 3, 1, 1, 128)
    p256 = tiles.cache_path(tmp_path, "s", 3, 1, 1, 256)
    p256.parent.mkdir(parents=True, exist_ok=True)
    os.replace(p128, p256)
    with pytest.raises(ValueError):
        tiles.get_tile("s", 3, 1, 1, tmp_path, offline=True)


def test_outside_the_world_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        tiles.mosaic("s", 1, -10, 0, 100, 100, tmp_path, offline=True)


def test_too_many_tiles_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        tiles.mosaic("s", 10, 0, 0, 256 * 30, 256 * 30, tmp_path, offline=True, max_tiles=100)


def test_url_for_both_tile_sizes():
    assert tiles.tile_url("https://h/styles", "a", 3, 4, 5, 256) == "https://h/styles/a/3/4/5.png"
    assert tiles.tile_url("https://h/styles", "a", 3, 4, 5, 512) == "https://h/styles/a/512/3/4/5.png"


@pytest.mark.skipif(os.environ.get("GEOREF_NETWORK") != "1", reason="set GEOREF_NETWORK=1 to fetch a real tile")
def test_fetch_real_tile(tmp_path):
    img = tiles.get_tile("osm-liberty", 14, 14552, 6451, tmp_path)
    assert img.shape == (256, 256, 3)
    assert Path(tiles.cache_path(tmp_path, "osm-liberty", 14, 14552, 6451, 256)).exists()
