# uvx --with numpy --with opencv-python-headless --with scikit-image --with pytest pytest scripts/test_register_cross_style.py
import cv2
import numpy as np
import pytest

import register_cross_style as rcs
import webmercator as wm

Z = 16
OX, OY = 58000 * 256, 25800 * 256

STYLE_A = {"bg": (242, 239, 233), "water": (170, 211, 223), "road": (255, 220, 120), "block": (217, 208, 201),
           "park": (200, 230, 190), "extra": 0}
STYLE_B = {"bg": (224, 224, 224), "water": (120, 165, 230), "road": (232, 146, 162), "block": (190, 170, 150),
           "park": (150, 200, 140), "extra": 2}


def scene(style, seed=0, w=1600, h=1200):
    """The same geometry drawn in a given palette and line width."""
    g = np.random.default_rng(seed)
    img = np.full((h, w, 3), style["bg"], np.uint8)
    for _ in range(60):
        p = tuple(int(v) for v in g.integers(0, [w, h]))
        s = tuple(int(v) for v in g.integers(20, 70, 2))
        cv2.rectangle(img, p, (p[0] + s[0], p[1] + s[1]), style["block"], -1)
    for _ in range(8):
        c = tuple(int(v) for v in g.integers(0, [w, h]))
        cv2.circle(img, c, int(g.integers(30, 70)), style["park"], -1)
    river = np.array([[0, 300], [400, 380], [800, 330], [1200, 450], [1600, 420]], np.int32)
    cv2.polylines(img, [river], False, style["water"], 40)
    for _ in range(5):
        c = tuple(int(v) for v in g.integers(0, [w, h]))
        cv2.ellipse(img, c, (int(g.integers(30, 80)), int(g.integers(20, 50))), float(g.uniform(0, 180)), 0, 360,
                    style["water"], -1)
    for _ in range(40):
        a = tuple(int(v) for v in g.integers(0, [w, h]))
        b = tuple(int(v) for v in g.integers(0, [w, h]))
        cv2.line(img, a, b, style["road"], 4 + style["extra"])
    return img


def meta():
    mx0, my0 = wm.global_px_to_mercator(OX, OY, Z)
    res = 2 * wm.ORIGIN / wm.world_px(Z)
    return {"crs": "EPSG:3857", "geotransform": [float(mx0), res, 0.0, float(my0), 0.0, -res]}


def warp(ref, D, W, H):
    M = np.array([[1, 0, -0.5], [0, 1, -0.5], [0, 0, 1.0]]) @ D @ np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1.0]])
    return cv2.warpPerspective(ref, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)


def gcp_errors(ans, D):
    cr = np.array([[g["col"], g["row"]] for g in ans["gcps"]])
    lon = np.array([g["lon"] for g in ans["gcps"]])
    lat = np.array([g["lat"] for g in ans["gcps"]])
    gx, gy = wm.lonlat_to_global_px(lon, lat, Z)
    q = np.column_stack([cr, np.ones(len(cr))]) @ D.T
    want = q[:, :2] / q[:, 2:] + [OX, OY]
    return np.column_stack([gx - want[:, 0], gy - want[:, 1]])


# task pixel (corner) p shows reference corner D p: rotated 12 degrees, 1.05 x, a little perspective
TH = np.radians(12)
D = np.array([[1.05 * np.cos(TH), -1.05 * np.sin(TH), 420], [1.05 * np.sin(TH), 1.05 * np.cos(TH), 250],
              [2e-5, -1e-5, 1.0]])


def test_other_style_gives_unbiased_control_points():
    ref = scene(STYLE_A)
    task = warp(scene(STYLE_B), D, 900, 700)
    ans = rcs.register(task, ref, meta())
    assert ans["status"] == "ok", ans.get("reason")
    e = gcp_errors(ans, D)
    d = np.hypot(e[:, 0], e[:, 1])
    assert len(d) >= 12
    assert np.median(d) < 1.0
    assert np.abs(e.mean(axis=0)).max() < 0.5  # no systematic offset from pixel-centre/corner slips
    assert d.max() < 3.0


def test_corner_to_index_matches_a_pure_shift():
    M = np.array([[1.0, 0, 10.0], [0, 1.0, 5.0]])
    np.testing.assert_allclose(rcs.corner_to_index(M), M)  # translation is the same in both conventions
    S = np.array([[2.0, 0, 0], [0, 2.0, 0]])
    # corner (0, 0) -> (0, 0); index (0, 0) is corner (0.5, 0.5) -> (1, 1) -> index (0.5, 0.5)
    np.testing.assert_allclose(rcs.corner_to_index(S) @ [0, 0, 1], [0.5, 0.5])


def test_water_mask():
    img = np.zeros((10, 30, 3), np.uint8)
    img[:, :10] = STYLE_A["water"]
    img[:, 10:20] = STYLE_B["water"]
    img[:, 20:] = STYLE_A["park"]
    m = rcs.water_mask(img)
    assert m[:, :20].mean() > 0.9 and m[:, 20:].max() == 0


def test_no_water_is_a_declared_failure():
    a = scene(STYLE_A)
    a[(a == STYLE_A["water"]).all(axis=-1)] = STYLE_A["bg"]
    ans = rcs.register(warp(a, D, 900, 700), a, meta())
    assert ans["status"] == "failed" and "water" in ans["reason"]


def test_a_dark_blue_background_is_not_water():
    dark = np.full((700, 900, 3), (40, 60, 120), np.uint8)
    dark[:] = (60, 80, 140)
    ans = rcs.register(dark, scene(STYLE_A), meta())
    assert ans["status"] == "failed"


def test_another_place_is_a_declared_failure():
    ref = scene(STYLE_A, seed=0)
    task = warp(scene(STYLE_B, seed=5), D, 900, 700)
    ans = rcs.register(task, ref, meta())
    assert ans["status"] == "failed", ans["stats"]


def lines_scene(width, seed=0, w=1600, h=1200, bg=(68, 80, 110), fg=(30, 30, 255)):
    """A map of lines only (like the railways style), drawn at a given line width."""
    g = np.random.default_rng(seed)
    img = np.full((h, w, 3), bg, np.uint8)
    for _ in range(35):
        pts = np.cumsum(g.normal(0, 60, (6, 2)), axis=0) + g.integers(0, [w, h])
        cv2.polylines(img, [pts.astype(np.int32)], False, fg, width)
    return img


def test_lines_mode_matches_lines_of_another_width():
    ref = lines_scene(1)
    task = warp(lines_scene(4, fg=(70, 130, 200)), D, 900, 700)
    ans = rcs.register(task, ref, meta(), mask="lines")
    assert ans["status"] == "ok", ans.get("reason")
    e = gcp_errors(ans, D)
    d = np.hypot(e[:, 0], e[:, 1])
    assert len(d) >= 12 and np.median(d) < 1.5 and np.abs(e.mean(axis=0)).max() < 0.7


def test_line_mask_is_width_independent():
    a = rcs.line_mask(lines_scene(1))
    b = rcs.line_mask(lines_scene(5))
    inter = (a & b).sum() / max(1, (a | b).sum())
    assert inter > 0.5


def test_consistent_patches_tell_a_place_from_scatter():
    r = np.random.default_rng(3)
    src = r.uniform(0, 900, (40, 2))
    q = np.column_stack([src, np.ones(40)]) @ D.T
    good = [(a, b) for a, b in zip(src, q[:, :2] / q[:, 2:] + r.normal(0, 0.5, (40, 2)))]
    _, n_good = rcs.consistent_patches(good)
    assert n_good >= 38 and rcs.place_is_supported(n_good, 40)
    bad = [(a, a + r.uniform(-48, 48, 2)) for a in src]  # each patch found its own shift: another place
    _, n_bad = rcs.consistent_patches(bad)
    assert not rcs.place_is_supported(n_bad, 40)
    assert not rcs.place_is_supported(13, 40)  # enough patches but under half of them
