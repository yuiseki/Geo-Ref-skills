# uvx --with numpy --with pillow --with pytest pytest scripts/test_fetch_reference.py
import json

import numpy as np
import pytest
from PIL import Image

import fetch_reference
import tiles
import webmercator as wm


def fill(cache, style, z, txs, tys):
    for tx in txs:
        for ty in tys:
            v, u = np.mgrid[0:256, 0:256]
            img = np.stack([u, v, np.full_like(u, (tx + 3 * ty) % 256)], -1).astype(np.uint8)
            p = tiles.cache_path(cache, style, z, tx, ty)
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(img).save(p)


def test_geotransform_maps_pixels_to_the_right_place(tmp_path):
    z = 14
    fill(tmp_path / "c", "s", z, range(14550, 14555), range(6449, 6454))
    bbox = (139.73, 35.67, 139.77, 35.70)
    meta = fetch_reference.build("s", z, bbox, tmp_path / "c", tmp_path / "out", offline=True)
    img = np.asarray(Image.open(tmp_path / "out" / "reference.png"))
    assert img.shape == (meta["height"], meta["width"], 3)
    gt = meta["geotransform"]
    assert json.loads((tmp_path / "out" / "reference.json").read_text())["geotransform"] == gt
    # the centre of pixel (i, j) in metres, back to a global pixel, must be the pixel the image holds there
    for i, j in [(0, 0), (17, 203), (meta["width"] - 1, meta["height"] - 1)]:
        mx = gt[0] + (i + 0.5) * gt[1]
        my = gt[3] + (j + 0.5) * gt[5]
        gx, gy = wm.mercator_to_global_px(mx, my, z)
        gx, gy = int(np.floor(gx)), int(np.floor(gy))
        assert tuple(img[j, i]) == (gx % 256, gy % 256, (gx // 256 + 3 * (gy // 256)) % 256)
    # the requested bbox lies inside the image
    lon_w, lat_n = wm.mercator_to_lonlat(gt[0], gt[3])
    lon_e, lat_s = wm.mercator_to_lonlat(gt[0] + meta["width"] * gt[1], gt[3] + meta["height"] * gt[5])
    assert lon_w <= bbox[0] and lat_s <= bbox[1] and lon_e >= bbox[2] and lat_n >= bbox[3]


def test_bbox_order_is_checked(tmp_path):
    with pytest.raises(ValueError):
        fetch_reference.build("s", 14, (35.67, 139.73, 35.70, 139.77), tmp_path, tmp_path / "o", offline=True)
    with pytest.raises(ValueError):
        fetch_reference.build("s", 14, (139.77, 35.67, 139.73, 35.70), tmp_path, tmp_path / "o", offline=True)
