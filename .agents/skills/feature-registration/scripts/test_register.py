# uvx --with numpy --with opencv-python-headless --with pytest pytest scripts/test_register.py
import cv2
import numpy as np
import pytest

import register
import webmercator as wm

Z = 16
OX, OY = 58000 * 256, 25800 * 256  # global pixel of the reference's top-left corner (near Tokyo)


def scene(w=1400, h=1100, seed=0):
    """A synthetic map-like picture: random lines, boxes and labels-like blobs."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 240, np.uint8)
    for _ in range(250):
        p1 = tuple(int(v) for v in rng.integers(0, [w, h]))
        p2 = tuple(int(v) for v in rng.integers(0, [w, h]))
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.line(img, p1, p2, color, int(rng.integers(1, 6)))
    for _ in range(300):
        p = tuple(int(v) for v in rng.integers(0, [w, h]))
        s = tuple(int(v) for v in rng.integers(4, 30, 2))
        cv2.rectangle(img, p, (p[0] + s[0], p[1] + s[1]), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    for _ in range(150):
        p = tuple(int(v) for v in rng.integers(0, [w, h]))
        cv2.putText(img, str(int(rng.integers(0, 999))), p, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1)
    return img


def meta():
    mx0, my0 = wm.global_px_to_mercator(OX, OY, Z)
    res = 2 * wm.ORIGIN / wm.world_px(Z)
    return {"crs": "EPSG:3857", "geotransform": [float(mx0), res, 0.0, float(my0), 0.0, -res]}


def warp(ref, D, W, H):
    """Task pixel (corner coords) p shows reference corner coords D p."""
    M = np.array([[1, 0, -0.5], [0, 1, -0.5], [0, 0, 1.0]]) @ D @ np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1.0]])
    return cv2.warpPerspective(ref, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)


def check_answer(ans, D):
    assert ans["status"] == "ok", ans
    cr = np.array([[g["col"], g["row"]] for g in ans["gcps"]])
    lon = np.array([g["lon"] for g in ans["gcps"]])
    lat = np.array([g["lat"] for g in ans["gcps"]])
    gx, gy = wm.lonlat_to_global_px(lon, lat, Z)
    q = np.column_stack([cr, np.ones(len(cr))]) @ D.T
    want = q[:, :2] / q[:, 2:] + [OX, OY]
    err = np.hypot(gx - want[:, 0], gy - want[:, 1])
    return err


# SIFT localises keypoints to sub-pixel, ORB to whole pixels; ORB measured median 0.57, max 2.55 px (2026-11-03)
@pytest.mark.parametrize("detector,median_px,max_px", [("sift", 0.5, 2.0), ("orb", 1.0, 3.5)])
def test_recovers_a_known_homography(detector, median_px, max_px):
    ref = scene()
    th = np.radians(12)
    D = np.array([[1.1 * np.cos(th), -np.sin(th), 300], [np.sin(th), 0.95 * np.cos(th), 200], [3e-5, -2e-5, 1.0]])
    task = warp(ref, D, 800, 600)
    ans = register.register(task, ref, meta(), detector)
    err = check_answer(ans, D)
    assert len(err) >= 40
    assert np.median(err) < median_px
    assert err.max() < max_px
    cr = np.array([[g["col"], g["row"]] for g in ans["gcps"]])
    assert cr[:, 0].min() < 200 and cr[:, 0].max() > 600 and cr[:, 1].min() < 150 and cr[:, 1].max() > 450


def test_unrelated_image_is_a_declared_failure():
    ref = scene(seed=1)
    task = warp(scene(seed=2), np.eye(3), 800, 600)
    ans = register.register(task, ref, meta(), "sift")
    assert ans["status"] == "failed"
    assert ans["gcps"] == []


def test_thin_spreads_points():
    rng = np.random.default_rng(0)
    pts = np.vstack([rng.uniform(0, 50, (500, 2)), rng.uniform(0, 1000, (50, 2))])
    keep = register.thin(pts, rng.uniform(size=len(pts)), 1000, 1000, bins=10, per_bin=4)
    crowded = (pts[keep] < 100).all(axis=1).sum()
    assert crowded <= 4
    assert len(keep) > 30
