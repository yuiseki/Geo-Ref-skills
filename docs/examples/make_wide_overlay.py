"""Draw a georeferenced map on a wide stretch of OpenStreetMap, so that it can be seen to lie where it belongs.

    uvx --with numpy --with opencv-python-headless --with pillow python docs/examples/make_wide_overlay.py \
        image.png answer.json out.jpg [--margin 0.25] [--style osm-liberty] [--width 1700] [--gcp-image gcps.jpg]

Reads the map image and the answer of name-gcps (its control points and method), builds a reference of OpenStreetMap
tiles that reaches `margin` of the map's size beyond each side of the map, puts the map back with the answer's own
transform and lays what is drawn on it (the roads, boundaries, coasts and labels, as distance from its ground colour)
on the reference in magenta. Where the map is right, its coasts, rivers and boundaries fall on the reference's own;
the reference stays in full strength outside the map's frame, so the match can be judged against its surroundings.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / ".agents/skills/georef-gates/scripts"))
sys.path.insert(0, str(ROOT / ".agents/skills/tile-reference/scripts"))
import fetch_reference as fr  # noqa: E402
import transforms as tf  # noqa: E402
import webmercator as wm  # noqa: E402
from make_example import MAGENTA, ink  # noqa: E402



def pick_zoom(width_m, target_px):
    """The zoom at which `width_m` metres of web mercator are about `target_px` pixels wide (256 px tiles)."""
    return max(1, round(math.log2(target_px * (2 * wm.ORIGIN) / (width_m * 256))))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("answer")
    ap.add_argument("out")
    ap.add_argument("--margin", type=float, default=0.25)
    ap.add_argument("--style", default="osm-liberty")
    ap.add_argument("--width", type=int, default=1700)
    ap.add_argument("--gcp-image", default=None, help="also write the map with its control points circled in red")
    ap.add_argument("--cache", default=str(ROOT / "tmp/tiles"))
    a = ap.parse_args()
    img = cv2.imread(a.image)
    ans = json.loads(Path(a.answer).read_text(encoding="utf-8"))
    cr = np.array([[g["col"], g["row"]] for g in ans["gcps"]])
    mx, my = wm.lonlat_to_mercator(np.array([g["lon"] for g in ans["gcps"]]), np.array([g["lat"] for g in ans["gcps"]]))
    if a.gcp_image:
        shown = img.copy()
        for c, r in cr:
            cv2.circle(shown, (int(c), int(r)), 6, (0, 0, 255), 2)
        cv2.imwrite(a.gcp_image, shown, [cv2.IMWRITE_JPEG_QUALITY, 85])
    merc = np.column_stack([mx, my])
    c0 = merc.mean(axis=0)
    H, W = img.shape[:2]
    # the footprint of the map in mercator metres (fitted about the centre, which keeps the numbers small)
    fp = tf.fit(ans["method"], cr, merc - c0).predict(np.array([[0, 0], [W, 0], [W, H], [0, H]], float)) + c0
    lo, hi = fp.min(axis=0), fp.max(axis=0)
    span = hi - lo
    lo, hi = lo - a.margin * span, hi + a.margin * span
    zoom = pick_zoom(float(hi[0] - lo[0]), a.width)
    (w, s), (e, n) = (wm.mercator_to_lonlat(*lo), wm.mercator_to_lonlat(*hi))
    out_dir = Path(a.out).parent / (Path(a.out).stem + "-ref")
    fr.build(a.style, zoom, (w, s, e, n), a.cache, out_dir)
    ref = cv2.imread(str(out_dir / "reference.png"))
    gt = json.loads((out_dir / "reference.json").read_text(encoding="utf-8"))["geotransform"]
    ref_px = np.column_stack([(mx - gt[0]) / gt[1], (my - gt[3]) / gt[5]])
    inv = tf.fit(ans["method"], ref_px, cr)
    fwd = tf.fit(ans["method"], cr, ref_px)
    rh, rw = ref.shape[:2]
    jj, ii = np.mgrid[0:rh, 0:rw]
    src = inv.predict(np.column_stack([ii.ravel() + 0.5, jj.ravel() + 0.5])) - 0.5
    mapx = src[:, 0].reshape(ii.shape).astype(np.float32)
    mapy = src[:, 1].reshape(ii.shape).astype(np.float32)
    back = cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    inside = cv2.remap(np.full((H, W), 255, np.uint8), mapx, mapy, cv2.INTER_NEAREST, borderValue=0) > 0
    t = ink(back).astype(np.float32)[..., None] / 255.0
    t = 1 - 0.85 * (1 - t)
    layer = t * 255.0 + (1 - t) * np.array(MAGENTA, np.float32)
    # inside the frame the reference is paled so that the magenta reads; outside it stays as it is
    base = cv2.addWeighted(ref, 0.55, np.full_like(ref, 255), 0.45, 0).astype(np.float32)
    over = (base * layer / 255.0).astype(np.uint8)
    res = ref.copy()
    res[inside] = over[inside]
    pts = np.round(fwd.predict(np.array([[0, 0], [W, 0], [W, H], [0, H]], float))).astype(np.int32)
    cv2.polylines(res, [pts], True, (0, 0, 255), 3)
    cv2.imwrite(a.out, res, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(json.dumps({"out": a.out, "zoom": zoom, "size": [rw, rh], "gcps": len(cr)}))


if __name__ == "__main__":
    main()
