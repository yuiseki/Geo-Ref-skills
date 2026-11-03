# uvx --with numpy --with pillow --with opencv-python-headless --with pyproj --with pytest pytest scripts/test_make_task.py
import json

import numpy as np
import pytest
from PIL import Image

import make_task
import score_task
import tiles
import webmercator as wm

Z = 15
CENTER = (139.7528, 35.6852)


def fill(cache, style="s"):
    cx, cy = wm.lonlat_to_global_px(*CENTER, Z)
    tx, ty = int(cx // 256), int(cy // 256)
    for x in range(tx - 6, tx + 7):
        for y in range(ty - 6, ty + 7):
            v, u = np.mgrid[0:256, 0:256]
            img = np.stack([u, v, np.full_like(u, (x + 3 * y) % 256)], -1).astype(np.uint8)
            p = tiles.cache_path(cache, style, Z, x, y)
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(img).save(p)


@pytest.mark.parametrize("kind", make_task.KINDS)
def test_task_pixels_show_the_true_place(tmp_path, kind):
    fill(tmp_path / "c")
    task, hint, truth = make_task.make("s", CENTER, Z, (300, 200), kind, 1.0, 3, tmp_path / "c",
                                       tmp_path / "task", tmp_path / "truth", offline=True, interp="nearest")
    D = np.array(truth["task_px_to_global_px"])
    rng = np.random.default_rng(0)
    bad = 0
    for _ in range(400):
        i, j = rng.integers(0, 300), rng.integers(0, 200)
        g = make_task.apply_h(D, np.array([[i + 0.5, j + 0.5]]))[0]
        gx, gy = int(np.floor(g[0])), int(np.floor(g[1]))
        want = (gx % 256, gy % 256, (gx // 256 + 3 * (gy // 256)) % 256)
        bad += tuple(task[j, i]) != want
    # nearest neighbour may pick the next pixel when the sample lands within float error of a pixel edge
    assert bad <= 4


def test_hint_contains_the_footprint_but_not_centred(tmp_path):
    fill(tmp_path / "c")
    _, hint, truth = make_task.make("s", CENTER, Z, (300, 200), "projective", 1.0, 5, tmp_path / "c",
                                    tmp_path / "task", tmp_path / "truth", offline=True)
    fp = np.array(truth["footprint_lonlat"])
    w, s, e, n = hint["bbox"]
    assert (fp[:, 0] > w).all() and (fp[:, 0] < e).all() and (fp[:, 1] > s).all() and (fp[:, 1] < n).all()
    assert abs((w + e) / 2 - fp[:, 0].mean()) > 1e-6
    assert "task_px_to_global_px" not in json.loads((tmp_path / "task" / "hint.json").read_text())


def answer_from_truth(truth, offset_px=(0.0, 0.0), n=6):
    W, H = truth["width"], truth["height"]
    cc, rr = np.meshgrid(np.linspace(10, W - 10, n), np.linspace(10, H - 10, n))
    cr = np.column_stack([cc.ravel(), rr.ravel()])
    g = make_task.apply_h(np.array(truth["task_px_to_global_px"]), cr) + offset_px
    lon, lat = wm.global_px_to_lonlat(g[:, 0], g[:, 1], truth["zoom"])
    return {"status": "ok", "image": {"width": W, "height": H}, "method": "projective", "crs": "EPSG:4326",
            "gcps": [{"col": c, "row": r, "lon": a, "lat": b} for (c, r), a, b in zip(cr.tolist(), lon, lat)]}


def test_score_of_the_true_answer_is_zero_and_a_shift_is_measured(tmp_path):
    fill(tmp_path / "c")
    _, _, truth = make_task.make("s", CENTER, Z, (300, 200), "projective", 1.0, 9, tmp_path / "c",
                                 tmp_path / "task", tmp_path / "truth", offline=True)
    r0 = score_task.score(answer_from_truth(truth), truth)
    assert r0["status"] == "scored" and r0["max_m"] < 0.01
    r1 = score_task.score(answer_from_truth(truth, (10.0, 0.0)), truth)
    want = 10 * wm.ground_resolution(CENTER[1], Z)
    assert r1["median_m"] == pytest.approx(want, rel=0.02)


def test_declared_failure_and_unfittable_are_not_distances(tmp_path):
    fill(tmp_path / "c")
    _, _, truth = make_task.make("s", CENTER, Z, (300, 200), "similarity", 0.5, 1, tmp_path / "c",
                                 tmp_path / "task", tmp_path / "truth", offline=True)
    assert score_task.score({"status": "failed", "reason": "x"}, truth)["status"] == "declared_failure"
    a = answer_from_truth(truth)
    a["gcps"] = a["gcps"][:3]
    assert score_task.score(a, truth)["status"] == "unfittable"
