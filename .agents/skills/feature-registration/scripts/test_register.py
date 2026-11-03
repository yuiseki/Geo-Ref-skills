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


def sparse_scene(w=1400, h=1100, seed=0, n_lines=40, n_rect=25):
    """Few features, like a map of farmland."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 240, np.uint8)
    for _ in range(n_lines):
        p1 = tuple(int(v) for v in rng.integers(0, [w, h]))
        p2 = tuple(int(v) for v in rng.integers(0, [w, h]))
        cv2.line(img, p1, p2, tuple(int(c) for c in rng.integers(0, 255, 3)), int(rng.integers(2, 6)))
    for _ in range(n_rect):
        p = tuple(int(v) for v in rng.integers(0, [w, h]))
        s = tuple(int(v) for v in rng.integers(6, 30, 2))
        cv2.rectangle(img, p, (p[0] + s[0], p[1] + s[1]), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    return img


def test_asift_solves_a_sparse_affine_case_that_plain_sift_cannot():
    # measured 2026-11-03: plain SIFT 4 distinct inliers, ASIFT 58 (aspect 1.6, shear 0.3)
    ref = sparse_scene()
    D = np.array([[1.6, 0.3, 250], [0, 1 / 1.6, 250], [0, 0, 1.0]])
    task = warp(ref, D, 800, 600)
    assert register.register(task, ref, meta(), "sift", asift="off")["status"] == "failed"
    ans = register.register(task, ref, meta(), "sift", asift="auto")
    assert ans["tool"]["asift"] == "on"
    assert ans["stats"]["plain_attempt"]["reason"]
    err = check_answer(ans, D)
    assert np.median(err) < 1.0
    assert err.max() < 3.0


def test_asift_on_unrelated_images_still_fails():
    ref = scene(seed=1)
    task = warp(scene(seed=2), np.eye(3), 800, 600)
    ans = register.register(task, ref, meta(), "sift", asift="on")
    assert ans["status"] == "failed"
    assert ans["stats"]["inlier_ratio"] < 0.1


def test_affine_views_follow_asift():
    v = register.affine_views()
    assert v[0] == (1.0, 0.0)
    assert sum(1 for t, _ in v if t == 2.0) == 5  # 72 / 2 = 36 degrees: 0, 36, ..., 144


@pytest.mark.parametrize("t,phi", [(1.0, 90.0), (1.0, 50.9), (2 ** 0.5, 50.9)])
def test_view_keypoints_map_back_without_bias(t, phi):
    # OpenCV SIFT reports keypoints 0.25 px off; through a rotated view the bias showed as 0.5 px at 90 degrees
    img = cv2.cvtColor(scene(), cv2.COLOR_RGB2GRAY)
    det = cv2.SIFT_create(nfeatures=20000)
    off = register.KEYPOINT_OFFSET["sift"]
    p0, d0 = register.detect_view(det, img, 1.0, 0.0, off)
    p, d = register.detect_view(det, img, t, phi, off)
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d, d0, k=2)
    good = [a for a, b in pairs if a.distance < 0.6 * b.distance]
    dv = np.array([p[g.queryIdx] - p0[g.trainIdx] for g in good])
    dv = dv[np.hypot(*dv.T) < 5]
    assert len(dv) > 500
    assert np.abs(dv.mean(axis=0)).max() < 0.06


def test_distinct_counts_one_inlier_per_place():
    pts = np.array([[10.2, 5.1], [10.4, 4.9], [30.0, 7.0], [10.1, 5.2], [50.0, 50.0]])
    mask = np.array([True, True, True, True, False])
    out = register.distinct(pts, mask)
    assert out.tolist() == [True, False, True, False, False]
