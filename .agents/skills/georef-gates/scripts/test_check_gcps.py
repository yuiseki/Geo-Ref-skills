# uvx --with numpy --with pytest pytest scripts/test_check_gcps.py
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import check_gcps
import webmercator as wm

HERE = Path(__file__).parent
W, H = 1000, 800
rng = np.random.default_rng(7)
# a mildly rotated map of Tokyo at about 2.4 m per pixel: image pixel to global pixel at z16
Z = 16
G0 = np.array(wm.lonlat_to_global_px(139.74, 35.70, Z))
ROT = np.radians(8.0)
M = 1.05 * np.array([[np.cos(ROT), -np.sin(ROT)], [np.sin(ROT), np.cos(ROT)]])


def truth(cr):
    g = cr @ M.T + G0
    return wm.global_px_to_lonlat(g[:, 0], g[:, 1], Z)


def answer(cr, method="projective", noise_px=0.3, status="ok"):
    lon, lat = truth(cr + rng.normal(0, noise_px, cr.shape))
    return {
        "status": status,
        "image": {"width": W, "height": H},
        "method": method,
        "crs": "EPSG:4326",
        "gcps": [{"col": float(c), "row": float(r), "lon": float(a), "lat": float(b)}
                 for (c, r), a, b in zip(cr, lon, lat)],
    }


def spread(n=40):
    return np.column_stack([rng.uniform(0, W, n), rng.uniform(0, H, n)])


def hint_around(margin=0.3):
    corners = np.array([[0, 0], [W, 0], [W, H], [0, H]], float)
    lon, lat = truth(corners)
    dw, dh = (lon.max() - lon.min()) * margin, (lat.max() - lat.min()) * margin
    return {"bbox": [lon.min() - dw, lat.min() - dh, lon.max() + dw, lat.max() + dh]}


def failed(report):
    return {g["name"] for g in report["gates"] if not g["passed"]}


def test_good_answer_passes():
    r = check_gcps.check(answer(spread()), hint_around())
    assert r["passed"], r
    assert failed(r) == set()


def test_declared_failure_is_reported_not_checked():
    r = check_gcps.check(answer(spread(), status="failed"))
    assert not r["passed"]
    assert r["declared_failure"]


def test_collinear_alone_fails_on_axis_ratio():
    t = rng.uniform(0, W, 30)
    cr = np.column_stack([t, 0.6 * t + rng.normal(0, 1.0, 30)])
    r = check_gcps.check(answer(cr), min_hull_fraction=0.0, min_quadrants=0)
    assert "spread" in failed(r)


def test_corner_cluster_alone_fails_on_hull():
    cr = np.column_stack([rng.uniform(0, 300, 30), rng.uniform(0, 250, 30)])
    r = check_gcps.check(answer(cr), min_axis_ratio=0.0, min_quadrants=0)
    assert "spread" in failed(r)


def test_left_half_alone_fails_on_quadrants():
    cr = np.column_stack([rng.uniform(0, 480, 40), rng.uniform(0, H, 40)])
    r = check_gcps.check(answer(cr), min_axis_ratio=0.0, min_hull_fraction=0.0)
    assert "spread" in failed(r)
    assert check_gcps.check(answer(cr), min_quadrants=2)["passed"]


def test_too_few_points():
    assert "enough_points" in failed(check_gcps.check(answer(spread(5))))


def test_collinear_points():
    t = rng.uniform(0, W, 30)
    cr = np.column_stack([t, 0.6 * t + rng.normal(0, 1.0, 30)])
    assert "spread" in failed(check_gcps.check(answer(cr)))


def test_points_in_one_corner():
    cr = np.column_stack([rng.uniform(0, 250, 30), rng.uniform(0, 200, 30)])
    assert "spread" in failed(check_gcps.check(answer(cr)))


def test_one_bad_point_fails_loo():
    a = answer(spread(30))
    a["gcps"][4]["lon"] += 0.001  # about 90 m, some 37 pixels
    r = check_gcps.check(a)
    assert "loo_residual" in failed(r)
    assert r["worst_point"] == 4


def test_mirrored_transform():
    a = answer(spread())
    for g in a["gcps"]:
        g["col"] = W - g["col"]
    assert "geometry" in failed(check_gcps.check(a))


def test_stretched_transform():
    cr = spread()
    a = answer(cr)
    for g, (c, _) in zip(a["gcps"], cr):
        g["col"] = c / 3.0 + 300
    assert "geometry" in failed(check_gcps.check(a))


def test_swapped_lon_lat_fails_range():
    a = answer(spread())
    for g in a["gcps"]:
        g["lon"], g["lat"] = g["lat"], g["lon"]
    assert "coordinates_in_range" in failed(check_gcps.check(a))


def test_outside_hint():
    h = hint_around()
    w, s, e, n = h["bbox"]
    h["bbox"] = [w + 0.05, s, e + 0.05, n]
    assert "inside_hint" in failed(check_gcps.check(answer(spread()), h))


def test_cli_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(answer(spread())), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(answer(spread(5))), encoding="utf-8")
    run = lambda p: subprocess.run([sys.executable, str(HERE / "check_gcps.py"), str(p)], capture_output=True, text=True)
    g, b = run(good), run(bad)
    assert g.returncode == 0, g.stderr
    assert json.loads(g.stdout)["passed"]
    assert b.returncode == 1
    assert not json.loads(b.stdout)["passed"]


def test_removed_fraction():
    a = answer(spread(40))
    a["refinement"] = {"n_input": 44, "removed": [{}] * 4}
    assert "removed_fraction" not in failed(check_gcps.check(a))
    a["refinement"] = {"n_input": 50, "removed": [{}] * 10}
    assert "removed_fraction" in failed(check_gcps.check(a))
    a["refinement"] = {"n_input": 44, "removed": [{}] * 3}  # counts do not add up
    assert "removed_fraction" in failed(check_gcps.check(a))
