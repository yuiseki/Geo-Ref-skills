"""Gates a georeferencing answer must pass before it is returned.

    python scripts/check_gcps.py answer.json [--hint hint.json]

answer.json:
    {"status": "ok" | "failed", "image": {"width": W, "height": H}, "method": "affine" | "projective" | "poly2" | "poly3",
     "crs": "EPSG:4326", "gcps": [{"col": c, "row": r, "lon": x, "lat": y}, ...]}
col and row are image pixel coordinates with (0, 0) at the top-left corner of the top-left pixel.
hint.json (optional): {"bbox": [west, south, east, north], ...}, the area the map is known to lie in.

Prints a JSON report and exits 0 when every gate passes, 1 otherwise. An answer whose status is
"failed" is reported as a declared failure (exit 1), not checked. No gate repairs the answer: a gate
that cannot be evaluated (the transform cannot be fitted) fails.
"""

import argparse
import json
import sys

import numpy as np

import transforms as tf
import webmercator as wm

DEFAULTS = {
    "points_per_parameter_point": 2.0,  # need this many times the method's minimum number of points
    "min_axis_ratio": 0.15,             # smaller / larger spread of the points (in image fractions)
    "min_hull_fraction": 0.25,          # convex hull of the points / image area
    "min_quadrants": 3,                 # image quadrants holding at least one point
    "max_loo_px": 3.0,                  # largest leave-one-out residual, in image pixels
    "max_anisotropy": 2.0,              # larger / smaller singular value of the local Jacobian
}


def hull_area(p):
    p = sorted(set(map(tuple, np.round(p, 9))))
    if len(p) < 3:
        return 0.0

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    h = np.array(lower[:-1] + upper[:-1])
    x, y = h[:, 0], h[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def gate(name, passed, **detail):
    return {"name": name, "passed": bool(passed), **detail}


def check(answer, hint=None, **opts):
    o = {**DEFAULTS, **opts}
    report = {"passed": False, "declared_failure": False, "gates": []}
    if answer.get("status") != "ok":
        report["declared_failure"] = True
        report["reason"] = answer.get("reason", "status is not ok")
        return report
    gates = report["gates"]
    W, H = float(answer["image"]["width"]), float(answer["image"]["height"])
    method = answer["method"]
    if answer.get("crs", "EPSG:4326") != "EPSG:4326":
        raise ValueError(f"control points must be in EPSG:4326 lon/lat, got {answer.get('crs')}")
    g = answer["gcps"]
    cr = np.array([[p["col"], p["row"]] for p in g], float).reshape(-1, 2)
    ll = np.array([[p["lon"], p["lat"]] for p in g], float).reshape(-1, 2)

    in_range = bool(len(ll)) and bool(np.all(np.abs(ll[:, 0]) <= 180) and np.all(np.abs(ll[:, 1]) <= wm.MAX_LAT))
    inside_image = bool(np.all((cr[:, 0] >= 0) & (cr[:, 0] <= W) & (cr[:, 1] >= 0) & (cr[:, 1] <= H)))
    gates.append(gate("coordinates_in_range", in_range and inside_image,
                      lonlat_in_range=in_range, pixels_inside_image=inside_image))

    need = int(np.ceil(tf.MIN_POINTS[method] * o["points_per_parameter_point"]))
    gates.append(gate("enough_points", len(cr) >= need, n=len(cr), need=need))

    if len(cr) >= 3:
        f = cr / [W, H]
        sv = np.linalg.svd(f - f.mean(axis=0), compute_uv=False)
        ratio = float(sv[1] / sv[0]) if sv[0] > 0 else 0.0
        hull = hull_area(f)
        quads = len({(c >= 0.5, r >= 0.5) for c, r in f})
    else:
        ratio, hull, quads = 0.0, 0.0, len(cr)
    gates.append(gate("spread", ratio >= o["min_axis_ratio"] and hull >= o["min_hull_fraction"]
                      and quads >= o["min_quadrants"], axis_ratio=ratio, hull_fraction=hull, quadrants=quads))

    if not in_range:
        for name in ("loo_residual", "geometry", "inside_hint"):
            gates.append(gate(name, False, error="coordinates out of range"))
        return report

    mx, my = wm.lonlat_to_mercator(ll[:, 0], ll[:, 1])
    dst = np.column_stack([mx, my])
    try:
        model = tf.fit(method, cr, dst)
        loo = tf.loo_residuals(method, cr, dst)
    except ValueError as e:
        for name in ("loo_residual", "geometry", "inside_hint"):
            gates.append(gate(name, False, error=f"cannot fit {method}: {e}"))
        return report

    cc, rr = np.meshgrid(np.linspace(0, W, 11), np.linspace(0, H, 11))
    grid = np.column_stack([cc.ravel(), rr.ravel()])
    J = model.jacobian(grid)
    det = np.linalg.det(J)
    sv = np.linalg.svd(J, compute_uv=False)
    aniso = float((sv[:, 0] / np.maximum(sv[:, 1], 1e-300)).max())
    gsd = float(np.sqrt(np.abs(np.linalg.det(model.jacobian(np.array([[W / 2, H / 2]]))[0]))))
    loo_px = loo / gsd
    report["worst_point"] = int(np.argmax(loo_px))
    gates.append(gate("loo_residual", loo_px.max() <= o["max_loo_px"], max_px=float(loo_px.max()),
                      median_px=float(np.median(loo_px)), limit_px=o["max_loo_px"], metres_per_px_mercator=gsd))

    pred = model.predict(grid)
    pred_ok = bool(np.all(np.abs(pred) <= wm.ORIGIN))
    # image rows grow downwards and northings upwards, so an unmirrored map has det < 0 everywhere
    gates.append(gate("geometry", bool(np.all(det < 0)) and aniso <= o["max_anisotropy"] and pred_ok,
                      mirrored_or_folded=bool(np.any(det >= 0)), anisotropy=aniso,
                      limit_anisotropy=o["max_anisotropy"], footprint_in_mercator=pred_ok))

    if hint is not None:
        lon, lat = wm.mercator_to_lonlat(pred[:, 0], pred[:, 1])
        w, s, e, n = hint["bbox"]
        inside = bool(np.all((lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)))
        gates.append(gate("inside_hint", inside, footprint=[float(lon.min()), float(lat.min()),
                                                             float(lon.max()), float(lat.max())], hint=[w, s, e, n]))
    report["passed"] = all(x["passed"] for x in gates)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("answer")
    ap.add_argument("--hint")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    a = ap.parse_args()
    with open(a.answer, encoding="utf-8") as fh:
        answer = json.load(fh)
    hint = None
    if a.hint:
        with open(a.hint, encoding="utf-8") as fh:
            hint = json.load(fh)
    opts = {k: getattr(a, k) for k in DEFAULTS}
    report = check(answer, hint, **opts)
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
