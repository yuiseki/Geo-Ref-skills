# uvx --with numpy --with pillow --with opencv-python-headless --with pyproj --with pytest pytest scripts/test_score_task.py
import numpy as np
import pytest

import make_task
import score_task
import webmercator as wm
from test_make_task import CENTER, Z, fill


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
