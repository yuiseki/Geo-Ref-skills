# uvx --with numpy --with pytest pytest scripts/test_refine_gcps.py
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

import refine_gcps
import webmercator as wm

HERE = Path(__file__).parent
W, H = 900, 700
Z = 16
G0 = np.array(wm.lonlat_to_global_px(139.74, 35.70, Z))


def answer(n, noise_px, seed=0, bad=None):
    """GCPs of a 1.1x scaled map; noise in reference pixels; bad: {index: offset_px}."""
    rng = np.random.default_rng(seed)
    cr = np.column_stack([rng.uniform(0, W, n), rng.uniform(0, H, n)])
    g = G0 + 1.1 * cr + rng.normal(0, noise_px, (n, 2))
    for i, off in (bad or {}).items():
        g[i] += off
    lon, lat = wm.global_px_to_lonlat(g[:, 0], g[:, 1], Z)
    return {"status": "ok", "image": {"width": W, "height": H}, "method": "projective", "crs": "EPSG:4326",
            "gcps": [{"col": float(c), "row": float(r), "lon": float(a), "lat": float(b)}
                     for (c, r), a, b in zip(cr, lon, lat)]}


def test_removes_the_planted_outliers_and_nothing_else():
    a = answer(60, 0.3, bad={3: (40, 0), 17: (0, -25), 41: (15, 15)})
    out = refine_gcps.refine(a)
    removed = sorted(r["index"] for r in out["refinement"]["removed"])
    assert removed == [3, 17, 41]
    assert len(out["gcps"]) == 57
    assert out["refinement"]["final_max_loo_px"] <= 3.0
    assert out["refinement"]["n_input"] == 60


def test_clean_points_are_left_alone():
    a = answer(60, 0.3)
    out = refine_gcps.refine(a)
    assert out["refinement"]["removed"] == []
    assert out["gcps"] == a["gcps"]


def test_noise_tail_of_many_points_is_trimmed_a_little():
    # many points with 1 px noise: the largest leave-one-out residual exceeds 3 px by chance alone
    a = answer(300, 1.0, seed=3)
    out = refine_gcps.refine(a)
    r = out["refinement"]
    assert r["initial_max_loo_px"] > 3.0
    assert 0 < len(r["removed"]) <= 0.05 * 300
    assert r["final_max_loo_px"] <= 3.0


def test_a_wrong_registration_stops_at_the_cap():
    # a third of the points from a different place: trimming must not make this pass
    rng = np.random.default_rng(5)
    bad = {i: tuple(rng.uniform(-60, 60, 2)) for i in range(0, 90, 3)}
    out = refine_gcps.refine(answer(90, 0.3, bad=bad))
    r = out["refinement"]
    assert len(r["removed"]) == 9  # 10% of 90
    assert r["stopped"] == "max_remove_fraction"
    assert r["final_max_loo_px"] > 3.0


def test_declared_failure_passes_through():
    a = {"status": "failed", "reason": "x", "gcps": []}
    assert refine_gcps.refine(a) == a


def test_cli(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(answer(40, 0.3, bad={5: (30, 0)})), encoding="utf-8")
    o = tmp_path / "b.json"
    r = subprocess.run([sys.executable, str(HERE / "refine_gcps.py"), str(p), "--out", str(o)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(o.read_text(encoding="utf-8"))
    assert [x["index"] for x in out["refinement"]["removed"]] == [5]


def test_unfittable_answer_is_passed_on_with_the_reason():
    a = answer(30, 0.3)
    for g in a["gcps"]:  # every point on one ground position: no transform
        g["lon"], g["lat"] = 139.74, 35.70
    out = refine_gcps.refine(a)
    assert out["refinement"]["stopped"] == "unfittable"
    assert "error" in out["refinement"]
    assert out["gcps"] == a["gcps"]
