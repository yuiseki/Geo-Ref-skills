"""Score a georeferencing answer against the task's true transform.

    python scripts/score_task.py answer.json truth.json

The answer's control points are fitted with the answer's own method (the same fitting the gates use),
then a 21 x 21 grid over the task image is mapped both by the fit and by the truth. Errors are geodesic
distances on WGS 84 in metres, and the largest error as a percentage of the image radius on the ground
(half the longer diagonal of the true footprint), the measure of Bahgat and Runfola (2021).
A declared failure and an answer that cannot be fitted are scored as such, never as a distance.
"""

import argparse
import json

import numpy as np
from pyproj import Geod

import transforms as tf
import webmercator as wm

GEOD = Geod(ellps="WGS84")


def apply_h(M, p):
    q = np.column_stack([p, np.ones(len(p))]) @ np.asarray(M).T
    return q[:, :2] / q[:, 2:]


def score(answer, truth, n=21):
    if answer.get("status") != "ok":
        return {"status": "declared_failure", "reason": answer.get("reason")}
    W, H = truth["width"], truth["height"]
    if (answer["image"]["width"], answer["image"]["height"]) != (W, H):
        return {"status": "wrong_image_size"}
    g = answer["gcps"]
    cr = np.array([[p["col"], p["row"]] for p in g], float).reshape(-1, 2)
    ll = np.array([[p["lon"], p["lat"]] for p in g], float).reshape(-1, 2)
    try:
        mx, my = wm.lonlat_to_mercator(ll[:, 0], ll[:, 1])
        model = tf.fit(answer["method"], cr, np.column_stack([mx, my]))
    except (ValueError, KeyError) as e:
        return {"status": "unfittable", "error": str(e)}
    cc, rr = np.meshgrid(np.linspace(0, W, n), np.linspace(0, H, n))
    grid = np.column_stack([cc.ravel(), rr.ravel()])
    gt = apply_h(truth["task_px_to_global_px"], grid)
    tlon, tlat = wm.global_px_to_lonlat(gt[:, 0], gt[:, 1], truth["zoom"], truth["tile_size"])
    pm = model.predict(grid)
    plon, plat = wm.mercator_to_lonlat(pm[:, 0], pm[:, 1])
    _, _, err = GEOD.inv(tlon, tlat, plon, plat)
    fp = np.array(truth["footprint_lonlat"])
    _, _, d1 = GEOD.inv(fp[0, 0], fp[0, 1], fp[2, 0], fp[2, 1])
    _, _, d2 = GEOD.inv(fp[1, 0], fp[1, 1], fp[3, 0], fp[3, 1])
    radius = max(d1, d2) / 2
    return {"status": "scored", "max_m": float(err.max()), "median_m": float(np.median(err)),
            "max_pct_radius": float(err.max() / radius * 100), "radius_m": float(radius), "n_gcps": len(cr)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("answer")
    ap.add_argument("truth")
    a = ap.parse_args()
    with open(a.answer, encoding="utf-8") as fa, open(a.truth, encoding="utf-8") as ft:
        print(json.dumps(score(json.load(fa), json.load(ft)), indent=2))


if __name__ == "__main__":
    main()
