"""Remove outlying control points one at a time, by their leave-one-out residual, and record what was removed.

    python scripts/refine_gcps.py answer.json --out refined.json [--target-loo-px 3] [--max-remove-fraction 0.1]

While the largest leave-one-out residual (in image pixels) is above the target, the point with that residual
is removed and all residuals are computed again. It stops when the target is met or when removing one more
point would exceed max-remove-fraction of the input. The output keeps the answer's fields, replaces "gcps"
with the points kept, and adds "refinement": the input count, every removed point with its index in the
input and its residual, and why it stopped. A declared failure is passed through unchanged.

Hitting the cap is not an error here; the answer is written and the gates decide. Removing points until
the residual fits is only safe because the fraction is capped and recorded.
"""

import argparse
import json
import sys

import numpy as np

import transforms as tf
import webmercator as wm


def loo_px(method, cr, dst, W, H):
    model = tf.fit(method, cr, dst)
    gsd = float(np.sqrt(abs(np.linalg.det(model.jacobian(np.array([[W / 2, H / 2]]))[0]))))
    return tf.loo_residuals(method, cr, dst) / gsd


def refine(answer, target_loo_px=3.0, max_remove_fraction=0.1):
    if answer.get("status") != "ok":
        return answer
    method = answer["method"]
    W, H = float(answer["image"]["width"]), float(answer["image"]["height"])
    g = answer["gcps"]
    cr = np.array([[p["col"], p["row"]] for p in g], float)
    ll = np.array([[p["lon"], p["lat"]] for p in g], float)
    mx, my = wm.lonlat_to_mercator(ll[:, 0], ll[:, 1])
    dst = np.column_stack([mx, my])
    n0 = len(cr)
    cap = int(np.floor(max_remove_fraction * n0))
    keep = np.arange(n0)
    removed = []
    try:
        r = loo_px(method, cr, dst, W, H)
    except ValueError as e:
        # not ours to repair: pass the answer on, say why, and let the gates fail it
        out = dict(answer)
        out["refinement"] = {"tool": "gcp-refinement", "n_input": n0, "removed": [], "stopped": "unfittable",
                             "error": str(e), "target_loo_px": target_loo_px,
                             "max_remove_fraction": max_remove_fraction}
        return out
    initial = float(r.max())
    stopped = "target_met"
    while r.max() > target_loo_px:
        if len(removed) >= cap:
            stopped = "max_remove_fraction"
            break
        if len(keep) <= tf.MIN_POINTS[method] + 1:
            stopped = "too_few_points"
            break
        worst = int(np.argmax(r))
        try:
            r_next = loo_px(method, cr[np.delete(keep, worst)], dst[np.delete(keep, worst)], W, H)
        except ValueError:
            stopped = "unfittable_after_removal"
            break
        removed.append({"index": int(keep[worst]), "loo_px": float(r[worst]), **g[keep[worst]]})
        keep = np.delete(keep, worst)
        r = r_next
    out = dict(answer)
    out["gcps"] = [g[i] for i in keep]
    out["refinement"] = {"tool": "gcp-refinement", "n_input": n0, "removed": removed, "stopped": stopped,
                         "target_loo_px": target_loo_px, "max_remove_fraction": max_remove_fraction,
                         "initial_max_loo_px": initial, "final_max_loo_px": float(r.max())}
    if len(out["gcps"]) + len(removed) != n0:
        raise RuntimeError("lost a control point")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("answer")
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-loo-px", type=float, default=3.0)
    ap.add_argument("--max-remove-fraction", type=float, default=0.1)
    a = ap.parse_args()
    with open(a.answer, encoding="utf-8") as fh:
        answer = json.load(fh)
    out = refine(answer, a.target_loo_px, a.max_remove_fraction)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    r = out.get("refinement", {})
    print(json.dumps({k: r.get(k) for k in ("n_input", "stopped", "initial_max_loo_px", "final_max_loo_px", "error")}
                     | {"removed": len(r.get("removed", []))}))
    sys.exit(0)


if __name__ == "__main__":
    main()
