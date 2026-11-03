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


def affine_views(tilts=(2 ** 0.5, 2.0)):
    """ASIFT views (Morel and Yu 2009): for tilt t, longitudes phi every 72/t degrees in [0, 180)."""
    views = [(1.0, 0.0)]
    for t in tilts:
        views += [(t, phi) for phi in np.arange(0.0, 180.0, 72.0 / t)]
    return views


# OpenCV's SIFT doubles the image for its first octave and reports keypoints 0.25 pixel right of and below the
# pixel-centre position (upsampling maps x to 2x + 0.5). The bias cancels between two unrotated images but not
# through rotated ASIFT views: measured on rotated copies it predicted 0.18, 0.30 and 0.50 pixel at 30, 50.9 and
# 90 degrees, observed 0.185, 0.30 and 0.501 (OpenCV 5.0.0, 2026-11-03). ORB is not corrected.
KEYPOINT_OFFSET = {"sift": 0.25, "orb": 0.0}


def detect_view(det, gray, t, phi, offset=0.0):
    """Keypoints of gray seen through rotation phi then compression 1/t along x, mapped back to gray's pixels."""
    if t == 1.0 and phi == 0.0:
        kps, desc = det.detectAndCompute(gray, None)
        return np.float32([k.pt for k in kps]).reshape(-1, 2) - offset, desc
    h, w = gray.shape
    A = cv2.getRotationMatrix2D((w / 2, h / 2), phi, 1.0)
    corners = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], float) @ A.T
    A[:, 2] -= corners.min(axis=0)
    size = np.ceil(corners.max(axis=0) - corners.min(axis=0)).astype(int)
    img = cv2.warpAffine(gray, A, (int(size[0]), int(size[1])), flags=cv2.INTER_LINEAR, borderValue=0)
    mask = cv2.warpAffine(np.full((h, w), 255, np.uint8), A, (int(size[0]), int(size[1])), flags=cv2.INTER_NEAREST)
    if t > 1.0:
        img = cv2.GaussianBlur(img, (0, 0), sigmaX=0.8 * np.sqrt(t * t - 1), sigmaY=0.01)
    img = cv2.resize(img, (max(1, int(size[0] / t)), int(size[1])), interpolation=cv2.INTER_LINEAR)
    mask = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
    kps, desc = det.detectAndCompute(img, mask)
    if desc is None:
        return np.zeros((0, 2), np.float32), None
    pts = np.float32([k.pt for k in kps]) - offset
    # undo the compression with the scale resize really used (the width was rounded to whole pixels, so it is
    # not exactly t; using t left a 0.6 pixel bias at t = sqrt 2, 2026-11-03). OpenCV coords are pixel centres.
    sx = size[0] / img.shape[1]
    pts[:, 0] = (pts[:, 0] + 0.5) * sx - 0.5
    Ai = cv2.invertAffineTransform(A)
    back = np.column_stack([pts, np.ones(len(pts))]) @ Ai.T
    return back.astype(np.float32), desc


def detect(det, gray, asift, offset=0.0):
    views = affine_views() if asift else [(1.0, 0.0)]
    pts, descs = [], []
    for t, phi in views:
        p, d = detect_view(det, gray, t, phi, offset)
        if d is not None and len(p):
            pts.append(p)
            descs.append(d)
    if not descs:
        return np.zeros((0, 2), np.float32), None
    return np.vstack(pts), np.vstack(descs)


def distinct(points, mask):
    """Keep one inlier per whole-pixel position: the same place seen through several ASIFT views is one piece
    of evidence, not several."""
    _, first = np.unique(np.round(points[mask]).astype(int), axis=0, return_index=True)
    out = np.zeros_like(mask)
    out[np.where(mask)[0][np.sort(first)]] = True
    return out


def gradient_image(img):
    """Edge strength in place of colour: the largest Sobel magnitude over the three channels, scaled so the 99th
    percentile is 255. It drops which colour a road or river is drawn in and keeps where its edges are."""
    f = img.astype(np.float32)
    gx = np.max([np.abs(cv2.Sobel(f[..., c], cv2.CV_32F, 1, 0)) for c in range(3)], axis=0)
    gy = np.max([np.abs(cv2.Sobel(f[..., c], cv2.CV_32F, 0, 1)) for c in range(3)], axis=0)
    m = np.hypot(gx, gy)
    top = np.percentile(m, 99)
    if top <= 0:
        return np.zeros_like(img)
    m = np.clip(m / top * 255.0, 0, 255).astype(np.uint8)
    return np.stack([m] * 3, axis=-1)


REPRESENTATIONS = {"gray": lambda x: x, "gradient": gradient_image}


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
             method="projective", bins=10, per_bin=4, asift="auto", min_inlier_ratio=0.1, representation="auto"):
    """asift: "off" plain features; "on" affine-simulated views of the image; "auto" plain, then on if it fails.
    representation: "gray" (the images as drawn), "gradient" (edge strength, for maps drawn in another style),
    or "auto": gray, then gradient if gray fails. Every attempt is kept in stats["attempts"]."""
    if representation == "auto":
        attempts = []
        for rep in ("gray", "gradient"):
            ans = register(image, ref_img, ref_meta, detector_name, ratio, ransac_px, min_inliers, method, bins,
                           per_bin, asift, min_inlier_ratio, rep)
            if ans["status"] == "ok":
                ans["stats"]["attempts"] = attempts
                return ans
            attempts.append({"representation": rep, "reason": ans.get("reason")})
        ans["stats"]["attempts"] = attempts
        return ans
    if representation not in REPRESENTATIONS:
        raise ValueError(f"representation must be auto or one of {sorted(REPRESENTATIONS)}")
    if asift == "auto":
        first = register(image, ref_img, ref_meta, detector_name, ratio, ransac_px, min_inliers, method, bins,
                         per_bin, "off", min_inlier_ratio, representation)
        if first["status"] == "ok":
            return first
        second = register(image, ref_img, ref_meta, detector_name, ratio, ransac_px, min_inliers, method, bins,
                          per_bin, "on", min_inlier_ratio, representation)
        second["stats"]["plain_attempt"] = {"reason": first.get("reason"), **first["stats"]}
        return second
    if asift not in ("on", "off"):
        raise ValueError(f"asift must be auto, on or off, got {asift}")
    H, W = image.shape[:2]
    det, norm = detector(detector_name)
    rep = REPRESENTATIONS[representation]
    g1 = cv2.cvtColor(rep(image), cv2.COLOR_RGB2GRAY)
    g2 = cv2.cvtColor(rep(ref_img), cv2.COLOR_RGB2GRAY)
    off = KEYPOINT_OFFSET[detector_name]
    p1all, d1 = detect(det, g1, asift == "on", off)
    p2all, d2 = detect(det, g2, False, off)
    stats = {"keypoints_image": len(p1all), "keypoints_reference": len(p2all), "asift": asift == "on",
             "representation": representation}
    base = {"image": {"width": W, "height": H}, "method": method, "crs": "EPSG:4326",
            "tool": {"name": "feature-registration", "detector": detector_name, "ratio": ratio,
                     "ransac_px": ransac_px, "asift": asift,
                     "representation": representation}, "stats": stats}
    if d1 is None or d2 is None or len(p1all) < 2 or len(p2all) < 2:
        return {**base, "status": "failed", "reason": "no keypoints", "gcps": []}
    pairs = cv2.BFMatcher(norm).knnMatch(d1, d2, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < ratio * p[1].distance]
    stats["ratio_matches"] = len(good)
    if len(good) < max(min_inliers, 4):
        return {**base, "status": "failed", "reason": f"{len(good)} matches after the ratio test", "gcps": []}
    p1 = np.float32([p1all[m.queryIdx] for m in good])
    p2 = np.float32([p2all[m.trainIdx] for m in good])
    Hm, mask = cv2.findHomography(p1, p2, cv2.USAC_MAGSAC, ransac_px)
    if Hm is None:
        return {**base, "status": "failed", "reason": "no consistent homography", "gcps": []}
    inl = mask.ravel().astype(bool)
    stats["inliers"] = int(inl.sum())
    # one-to-one: a repeated symbol in the image (bus stop icons, route shields) can all match one reference
    # point, and MAGSAC then accepts a degenerate homography that collapses the image onto it. In the level 1
    # negative controls, 21-167 image positions mapped to 1-2 reference positions (2026-11-03).
    inl = distinct(p2, distinct(p1, inl))
    stats["inliers_distinct"] = int(inl.sum())
    stats["inlier_ratio"] = float(inl.sum() / len(good))
    if inl.sum() < min_inliers or stats["inlier_ratio"] < min_inlier_ratio:
        return {**base, "status": "failed", "gcps": [],
                "reason": f"{int(inl.sum())} distinct inliers (need {min_inliers}), inlier ratio "
                          f"{stats['inlier_ratio']:.3f} (need {min_inlier_ratio})"}
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
    ap.add_argument("--min-inliers", type=int, default=20, help="distinct inlier positions needed")
    ap.add_argument("--min-inlier-ratio", type=float, default=0.1, help="inliers / ratio-test matches needed")
    ap.add_argument("--representation", default="auto", choices=["auto", "gray", "gradient"],
                    help="what to match: the images as drawn, or edge strength; auto tries gray first")
    ap.add_argument("--asift", default="auto", choices=["auto", "on", "off"],
                    help="affine-simulated views of the image (ASIFT); auto tries plain features first")
    a = ap.parse_args()
    ref = Path(a.ref)
    meta = json.loads((ref / "reference.json").read_text(encoding="utf-8"))
    if meta.get("crs") != "EPSG:3857":
        raise ValueError(f"reference must be EPSG:3857, got {meta.get('crs')}")
    ans = register(read_rgb(a.image), read_rgb(ref / "reference.png"), meta, a.detector, a.ratio, a.ransac_px,
                   a.min_inliers, a.method, asift=a.asift, min_inlier_ratio=a.min_inlier_ratio,
                   representation=a.representation)
    Path(a.out).write_text(json.dumps(ans, indent=2), encoding="utf-8")
    print(json.dumps({"status": ans["status"], "reason": ans.get("reason"), **ans["stats"]}))
    sys.exit(0 if ans["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
