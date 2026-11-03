"""Find control points between a map image and a georeferenced reference image by local features.

    python scripts/register.py image.png tmp/ref --out answer.json [--detector sift] [--method projective]

<ref> is a directory with reference.png and reference.json (EPSG:3857 geotransform, as written by
the tile-reference skill). Keypoints are matched with Lowe's ratio test, and a homography is fitted with
MAGSAC to keep geometrically consistent matches. The inliers, thinned to spread over the image, become
the control points of answer.json. Too few inliers writes a declared failure (status "failed") and exits 1;
it never writes a guess.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

import webmercator as wm


def detector(name):
    if name == "sift":
        return cv2.SIFT_create(nfeatures=20000), cv2.NORM_L2
    if name == "orb":
        return cv2.ORB_create(nfeatures=20000), cv2.NORM_HAMMING
    raise ValueError(f"unknown detector {name}")


def thin(points, scores, W, H, bins=10, per_bin=4):
    """Keep the best-scoring points in each cell of a bins x bins grid, so no area dominates."""
    cell = (np.minimum((points[:, 0] / W * bins).astype(int), bins - 1) * bins
            + np.minimum((points[:, 1] / H * bins).astype(int), bins - 1))
    keep = []
    for c in np.unique(cell):
        idx = np.where(cell == c)[0]
        keep.extend(idx[np.argsort(scores[idx])][:per_bin].tolist())
    return np.array(sorted(keep), int)


def register(image, ref_img, ref_meta, detector_name="sift", ratio=0.75, ransac_px=3.0, min_inliers=20,
             method="projective", bins=10, per_bin=4):
    H, W = image.shape[:2]
    det, norm = detector(detector_name)
    g1 = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    g2 = cv2.cvtColor(ref_img, cv2.COLOR_RGB2GRAY)
    k1, d1 = det.detectAndCompute(g1, None)
    k2, d2 = det.detectAndCompute(g2, None)
    stats = {"keypoints_image": len(k1), "keypoints_reference": len(k2)}
    base = {"image": {"width": W, "height": H}, "method": method, "crs": "EPSG:4326",
            "tool": {"name": "feature-registration", "detector": detector_name, "ratio": ratio,
                     "ransac_px": ransac_px}, "stats": stats}
    if d1 is None or d2 is None or len(k1) < 2 or len(k2) < 2:
        return {**base, "status": "failed", "reason": "no keypoints", "gcps": []}
    pairs = cv2.BFMatcher(norm).knnMatch(d1, d2, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < ratio * p[1].distance]
    stats["ratio_matches"] = len(good)
    if len(good) < max(min_inliers, 4):
        return {**base, "status": "failed", "reason": f"{len(good)} matches after the ratio test", "gcps": []}
    p1 = np.float32([k1[m.queryIdx].pt for m in good])
    p2 = np.float32([k2[m.trainIdx].pt for m in good])
    Hm, mask = cv2.findHomography(p1, p2, cv2.USAC_MAGSAC, ransac_px)
    if Hm is None:
        return {**base, "status": "failed", "reason": "no consistent homography", "gcps": []}
    inl = mask.ravel().astype(bool)
    stats["inliers"] = int(inl.sum())
    if inl.sum() < min_inliers:
        return {**base, "status": "failed", "reason": f"{int(inl.sum())} inliers < {min_inliers}", "gcps": []}
    # OpenCV keypoints are pixel-centre based; +0.5 gives corner coordinates
    c1 = p1[inl].astype(float) + 0.5
    c2 = p2[inl].astype(float) + 0.5
    dist = np.array([m.distance for m, ok in zip(good, inl) if ok])
    keep = thin(c1, dist, W, H, bins, per_bin)
    gt = ref_meta["geotransform"]
    mx = gt[0] + c2[keep, 0] * gt[1] + c2[keep, 1] * gt[2]
    my = gt[3] + c2[keep, 0] * gt[4] + c2[keep, 1] * gt[5]
    lon, lat = wm.mercator_to_lonlat(mx, my)
    stats["gcps"] = int(len(keep))
    gcps = [{"col": float(c), "row": float(r), "lon": float(a), "lat": float(b)}
            for (c, r), a, b in zip(c1[keep], lon, lat)]
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
    ap.add_argument("--detector", default="sift", choices=["sift", "orb"])
    ap.add_argument("--method", default="projective")
    ap.add_argument("--ratio", type=float, default=0.75)
    ap.add_argument("--ransac-px", type=float, default=3.0)
    ap.add_argument("--min-inliers", type=int, default=20)
    a = ap.parse_args()
    ref = Path(a.ref)
    meta = json.loads((ref / "reference.json").read_text(encoding="utf-8"))
    if meta.get("crs") != "EPSG:3857":
        raise ValueError(f"reference must be EPSG:3857, got {meta.get('crs')}")
    ans = register(read_rgb(a.image), read_rgb(ref / "reference.png"), meta, a.detector, a.ratio, a.ransac_px,
                   a.min_inliers, a.method)
    Path(a.out).write_text(json.dumps(ans, indent=2), encoding="utf-8")
    print(json.dumps({"status": ans["status"], "reason": ans.get("reason"), **ans["stats"]}))
    sys.exit(0 if ans["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
