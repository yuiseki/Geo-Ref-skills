"""Control points between a map and a reference drawn in another style.

    python scripts/register_cross_style.py image.png tmp/ref --out answer.json

Local features (SIFT) fail when the two maps are drawn differently (osm-carto against osm-liberty gave 4 or
fewer one-to-one inliers in every representation tried, 2026-11-03). This tool uses two things that survive
a change of style:

1. Coarse: water is drawn blue in nearly every map style. Both images are reduced to a blue mask, shrunk 4x,
   and a similarity (rotation every 3 degrees, scale every 5%) is searched, the translation by masked
   normalised cross-correlation.
2. Fine: the map is warped into the reference frame with the coarse similarity and both images' colours are
   clustered (k-means) separately. For patches on a grid, the shift that maximises the mutual information of
   the two label images is found; mutual information does not need to know which colour of one style is which
   colour of the other. Each patch gives one control point, measured independently, so the gates downstream can
   still check the points against each other.

It declares failure (status "failed") rather than guess when there is too little or too much blue (a dark blue
background, as in osm-fiord, is not water), when the coarse match is weak, or when too few patches have a clear
peak. Coordinates are pixel corners throughout ((0, 0) is the top-left corner of the top-left pixel).
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

import webmercator as wm

DEFAULTS = {
    "down": 4,                 # coarse search on images shrunk this many times
    "rotations": 48.0,         # search rotation in [-r, r] degrees
    "rotation_step": 3.0,
    "scale_min": 0.7, "scale_max": 1.45, "scale_step": 0.05,  # log steps
    "water_min": 0.005, "water_max": 0.5,  # fraction of each image that must look like water
    "min_coarse_score": 0.6,   # masked NCC of the blue masks at the best similarity
    "grid": (10, 8), "half": 64, "search": 48, "k": 8,
    "search2": 10,             # second pass search, around the first pass's homography
    "min_valid": 0.6,          # share of a patch that must be inside the map (patches at a rotated map's edge)
    "min_peak_ratio": 1.2,     # best MI / best MI more than 8 px away
    "min_gcps": 12,
}


def corner_to_index(M):
    """An affine in pixel-corner coordinates as the pixel-centre (index) affine cv2.warpAffine wants."""
    A = np.vstack([M, [0, 0, 1]])
    T = lambda d: np.array([[1, 0, d], [0, 1, d], [0, 0, 1.0]])
    return (T(-0.5) @ A @ T(0.5))[:2]


def water_mask(img):
    """Blue enough to be water: hue 170-250 degrees, saturation over 0.15, value over 0.35 (RGB input)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV_FULL).astype(np.float32)
    h, s, v = hsv[..., 0] * 360.0 / 256.0, hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
    m = ((h > 170) & (h < 250) & (s > 0.15) & (v > 0.35)).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def coarse_similarity(task_mask, ref_mask, o=DEFAULTS):
    """Search a similarity task -> ref on masks shrunk o["down"] times. Returns (score, 2x3 corner affine in full
    pixels, rotation, scale)."""
    f = o["down"]

    def prep(m):
        m = cv2.resize(m.astype(np.float32), None, fx=1 / f, fy=1 / f, interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(m, (0, 0), 2.0)

    a, b = prep(task_mask), prep(ref_mask)
    h, w = a.shape
    best = (-2.0, None, None, None)
    rots = np.arange(-o["rotations"], o["rotations"] + 1e-9, o["rotation_step"])
    scales = np.exp(np.arange(np.log(o["scale_min"]), np.log(o["scale_max"]) + 1e-9, o["scale_step"]))
    for th in rots:
        c, s_ = np.cos(np.radians(th)), np.sin(np.radians(th))
        for sc in scales:
            L = sc * np.array([[c, -s_], [s_, c]])
            corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], float) @ L.T
            t0 = -corners.min(axis=0)
            size = np.ceil(corners.max(axis=0) + t0).astype(int)
            Mc = np.column_stack([L, t0])
            Mi = corner_to_index(Mc)
            T = cv2.warpAffine(a, Mi, (int(size[0]), int(size[1])), flags=cv2.INTER_LINEAR)
            K = cv2.warpAffine(np.ones_like(a), Mi, (int(size[0]), int(size[1])), flags=cv2.INTER_NEAREST)
            K = cv2.erode(K, np.ones((3, 3), np.uint8))
            if K.sum() < 16 or T[K > 0].std() < 1e-6:
                continue
            ph, pw = T.shape
            pad = cv2.copyMakeBorder(b, ph, ph, pw, pw, cv2.BORDER_CONSTANT, value=0)
            res = cv2.matchTemplate(pad, T, cv2.TM_CCOEFF_NORMED, mask=K)
            # Over the zero padding the image under the template has almost no variance and the normalised score
            # blows up (2.99 was seen on a synthetic pair, 2026-11-03). Keep placements where at least half of the
            # template lies on the reference, and drop scores that are not correlations.
            inside = cv2.copyMakeBorder(np.ones_like(b), ph, ph, pw, pw, cv2.BORDER_CONSTANT, value=0)
            overlap = cv2.matchTemplate(inside, K, cv2.TM_CCORR) / float(K.sum())
            res[~np.isfinite(res) | (res > 1.0 + 1e-6) | (overlap < 0.5)] = -2
            _, mv, _, ml = cv2.minMaxLoc(res)
            if mv > best[0]:
                # template corner q sits at padded corner q + ml; ref coarse corner = that - (pw, ph)
                tc = t0 + np.array([ml[0] - pw, ml[1] - ph], float)
                full = np.column_stack([L, tc * f])  # corner coords scale exactly by f
                best = (float(mv), full, float(th), float(sc))
    return best


def kmeans_labels(img, k, seed=0):
    Z = img.reshape(-1, 3).astype(np.float32)
    rng = np.random.default_rng(seed)
    sample = Z[rng.choice(len(Z), min(20000, len(Z)), replace=False)]
    cv2.setRNGSeed(seed)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, _, centers = cv2.kmeans(sample, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    lab = np.empty(len(Z), np.int32)
    for i in range(0, len(Z), 200000):
        d = ((Z[i:i + 200000, None, :] - centers[None]) ** 2).sum(-1)
        lab[i:i + 200000] = d.argmin(1)
    return lab.reshape(img.shape[:2])


def mutual_information(a, b, k, mask=None):
    ab = a * k + b
    if mask is not None:
        ab = ab[mask]
    j = np.bincount(ab.ravel(), minlength=k * k).reshape(k, k).astype(np.float64)
    j /= j.sum()
    pa, pb = j.sum(1, keepdims=True), j.sum(0, keepdims=True)
    nz = j > 0
    return float((j[nz] * np.log(j[nz] / (pa @ pb)[nz])).sum())


def _peak_offset(sm, s0, sp):
    d = sm - 2 * s0 + sp
    return 0.0 if d >= 0 else float(np.clip(0.5 * (sm - sp) / d, -0.5, 0.5))


def homography_to_index(Hc):
    T = lambda d: np.array([[1, 0, d], [0, 1, d], [0, 0, 1.0]])
    return T(-0.5) @ Hc @ T(0.5)


def apply_h(Hm, p):
    q = Hm @ np.array([p[0], p[1], 1.0])
    return q[:2] / q[2]


def refine_patches(task, ref, A, o=DEFAULTS, search=None, la_task=None, lb=None):
    """Control points (task corner, ref corner) from patch-wise MI around A (task -> ref, corner coordinates;
    a 2x3 affine or a 3x3 homography)."""
    k, half = o["k"], o["half"]
    R = o["search"] if search is None else search
    H, W = task.shape[:2]
    rh, rw = ref.shape[:2]
    Hm = np.vstack([A, [0, 0, 1.0]]) if A.shape == (2, 3) else A
    if la_task is None:
        la_task = kmeans_labels(task, k)
    if lb is None:
        lb = kmeans_labels(ref, k)
    Mi = homography_to_index(Hm)
    la = cv2.warpPerspective(la_task.astype(np.float32), Mi, (rw, rh), flags=cv2.INTER_NEAREST).astype(np.int32)
    valid = cv2.warpPerspective(np.full((H, W), 255, np.uint8), Mi, (rw, rh), flags=cv2.INTER_NEAREST) > 0
    Hinv = np.linalg.inv(Hm)
    pts, info = [], []
    for gx in np.linspace(0.08, 0.92, o["grid"][0]):
        for gy in np.linspace(0.08, 0.92, o["grid"][1]):
            q = apply_h(Hm, (gx * W, gy * H))
            x0, y0 = int(round(q[0])), int(round(q[1]))
            if x0 - half - R < 0 or y0 - half - R < 0 or x0 + half + R > rw or y0 + half + R > rh:
                continue
            pv = valid[y0 - half:y0 + half, x0 - half:x0 + half]
            if pv.mean() < o["min_valid"]:
                continue
            pa = la[y0 - half:y0 + half, x0 - half:x0 + half]
            if len(np.unique(pa[pv])) < 2:
                continue

            def score(dx, dy):
                return mutual_information(pa, lb[y0 + dy - half:y0 + dy + half, x0 + dx - half:x0 + dx + half], k, pv)

            S = np.full((2 * R + 1, 2 * R + 1), -np.inf)
            step = 3 if R > 8 else 1
            for dy in range(-R, R + 1, step):
                for dx in range(-R, R + 1, step):
                    S[dy + R, dx + R] = score(dx, dy)
            iy, ix = np.unravel_index(np.argmax(S), S.shape)
            for dy in range(iy - R - 3, iy - R + 4):
                for dx in range(ix - R - 3, ix - R + 4):
                    if -R <= dy <= R and -R <= dx <= R and not np.isfinite(S[dy + R, dx + R]):
                        S[dy + R, dx + R] = score(dx, dy)
            iy, ix = np.unravel_index(np.argmax(S), S.shape)
            best = S[iy, ix]
            far = S.copy()
            far[max(0, iy - 8):iy + 9, max(0, ix - 8):ix + 9] = -np.inf
            second = far[np.isfinite(far)].max() if np.isfinite(far).any() else 0.0
            ratio = best / max(second, 1e-9)
            if not (0 < iy < 2 * R and 0 < ix < 2 * R):
                continue  # at the edge of the search: not a peak
            nb = [S[iy, ix - 1], S[iy, ix + 1], S[iy - 1, ix], S[iy + 1, ix]]
            if not all(np.isfinite(nb)):
                for (dx, dy) in [(ix - R - 1, iy - R), (ix - R + 1, iy - R), (ix - R, iy - R - 1), (ix - R, iy - R + 1)]:
                    S[dy + R, dx + R] = score(dx, dy)
                nb = [S[iy, ix - 1], S[iy, ix + 1], S[iy - 1, ix], S[iy + 1, ix]]
            sx = _peak_offset(nb[0], best, nb[1])
            sy = _peak_offset(nb[2], best, nb[3])
            info.append({"mi": float(best), "peak_ratio": float(ratio)})
            if ratio < o["min_peak_ratio"]:
                continue
            task_pt = apply_h(Hinv, (x0, y0))
            ref_pt = np.array([x0 + ix - R + sx, y0 + iy - R + sy])
            pts.append((task_pt, ref_pt))
    return pts, info, la_task, lb


def register(image, ref_img, ref_meta, **opts):
    o = {**DEFAULTS, **opts}
    H, W = image.shape[:2]
    base = {"image": {"width": W, "height": H}, "method": "projective", "crs": "EPSG:4326",
            "tool": {"name": "cross-style-registration", **{k: (list(v) if isinstance(v, tuple) else v)
                                                            for k, v in o.items()}}}
    wa, wb = water_mask(image), water_mask(ref_img)
    stats = {"water_image": float(wa.mean()), "water_reference": float(wb.mean())}
    base["stats"] = stats
    for name, frac in (("image", wa.mean()), ("reference", wb.mean())):
        if not (o["water_min"] <= frac <= o["water_max"]):
            return {**base, "status": "failed", "gcps": [],
                    "reason": f"water covers {frac:.3f} of the {name} (need {o['water_min']}-{o['water_max']})"}
    score, A, th, sc = coarse_similarity(wa, wb, o)
    stats.update(coarse_score=score, coarse_rotation=th, coarse_scale=sc)
    if A is None or score < o["min_coarse_score"]:
        return {**base, "status": "failed", "gcps": [], "reason": f"coarse match {score:.3f} < {o['min_coarse_score']}"}
    pts, info, la_task, lb = refine_patches(image, ref_img, A, o)
    stats.update(patches_pass1=len(info), gcps_pass1=len(pts))
    # second pass: a homography from the first pass's points takes out most of the local scale and shear, so
    # the patches line up and the mutual-information peaks sharpen; search only a little around it
    if len(pts) >= 8:
        src = np.float32([p for p, _ in pts])
        dst = np.float32([q for _, q in pts])
        Hm, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
        if Hm is not None and mask.sum() >= 8:
            pts2, info2, _, _ = refine_patches(image, ref_img, Hm, o, search=o["search2"], la_task=la_task, lb=lb)
            pts, info = pts2, info2
            stats["second_pass"] = True
    stats.update(patches=len(info), gcps=len(pts))
    if len(pts) < o["min_gcps"]:
        return {**base, "status": "failed", "gcps": [], "reason": f"{len(pts)} patches with a clear peak < {o['min_gcps']}"}
    gt = ref_meta["geotransform"]
    gcps = []
    for (tc, tr), (rc, rr) in pts:
        mx = gt[0] + rc * gt[1] + rr * gt[2]
        my = gt[3] + rc * gt[4] + rr * gt[5]
        lon, lat = wm.mercator_to_lonlat(mx, my)
        gcps.append({"col": float(tc), "row": float(tr), "lon": float(lon), "lat": float(lat)})
    return {**base, "status": "ok", "gcps": gcps}


def read_rgb(path):
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("ref", help="directory with reference.png and reference.json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ref = Path(a.ref)
    meta = json.loads((ref / "reference.json").read_text(encoding="utf-8"))
    if meta.get("crs") != "EPSG:3857":
        raise ValueError(f"reference must be EPSG:3857, got {meta.get('crs')}")
    ans = register(read_rgb(a.image), read_rgb(ref / "reference.png"), meta)
    Path(a.out).write_text(json.dumps(ans, indent=2), encoding="utf-8")
    print(json.dumps({"status": ans["status"], "reason": ans.get("reason"), **ans["stats"]}))
    sys.exit(0 if ans["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
