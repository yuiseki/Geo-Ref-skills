"""Draw the README example figures from a finished run.

    uvx --with numpy --with opencv-python-headless python docs/examples/make_example.py \
        tmp/matrix/level1/<task-id> docs/examples/<name>

Reads <run>/task/image.png, <run>/run/ref/, <run>/run/refined.json and <run>/run/score.json, and writes
<name>-input.jpg (the distorted map with its control points) and <name>-magenta.jpg (the map put back with the
answer's own transform, laid over the reference at half opacity, so misalignment shows as doubled lines).
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents" / "skills" / "georef-gates" / "scripts"))
import transforms as tf  # noqa: E402
import webmercator as wm  # noqa: E402


MAGENTA = (210, 0, 200)  # BGR


def ink(img):
    """How far each pixel is from the map's ground colour (its most common colour), as dark ink on white.

    Works the same for light and dark styles: whatever is drawn on the ground shows dark."""
    q = (img // 8).reshape(-1, 3).astype(np.int32)
    code = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]
    ground = np.array(np.unravel_index(np.bincount(code).argmax(), (32, 32, 32))) * 8 + 4
    d = np.linalg.norm(img.astype(np.float32) - ground, axis=-1)
    # a fixed scale, not a percentile: on busy colour maps a percentile turns every faint fill into full ink
    return (255 - np.clip((d - 30) / 120, 0, 1) * 255).astype(np.uint8)


def main(run, out):
    run, out = Path(run), Path(out)
    img = cv2.imread(str(run / "task" / "image.png"))
    ref = cv2.imread(str(run / "run" / "ref" / "reference.png"))
    meta = json.loads((run / "run" / "ref" / "reference.json").read_text(encoding="utf-8"))
    ans = json.loads((run / "run" / "refined.json").read_text(encoding="utf-8"))
    if ans["status"] != "ok":
        raise SystemExit("the answer is a declared failure; nothing to draw")
    cr = np.array([[g["col"], g["row"]] for g in ans["gcps"]])
    ll = np.array([[g["lon"], g["lat"]] for g in ans["gcps"]])
    mx, my = wm.lonlat_to_mercator(ll[:, 0], ll[:, 1])
    gt = meta["geotransform"]
    ref_px = np.column_stack([(mx - gt[0]) / gt[1], (my - gt[3]) / gt[5]])

    shown = img.copy()
    for c, r in cr:
        cv2.circle(shown, (int(c), int(r)), 6, (0, 0, 255), 2)
    cv2.imwrite(str(out) + "-input.jpg", shown, [cv2.IMWRITE_JPEG_QUALITY, 85])

    # reference pixel -> map pixel, fitted from the same control points (corner coordinates on both sides)
    inv = tf.fit(ans["method"], ref_px, cr)
    H, W = img.shape[:2]
    fwd = tf.fit(ans["method"], cr, ref_px)
    fp = fwd.predict(np.array([[0, 0], [W, 0], [W, H], [0, H]], float))
    x0, y0 = np.floor(fp.min(axis=0)).astype(int) - 20
    x1, y1 = np.ceil(fp.max(axis=0)).astype(int) + 20
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, ref.shape[1]), min(y1, ref.shape[0])
    jj, ii = np.mgrid[y0:y1, x0:x1]
    src = inv.predict(np.column_stack([ii.ravel() + 0.5, jj.ravel() + 0.5])) - 0.5
    mapx = src[:, 0].reshape(ii.shape).astype(np.float32)
    mapy = src[:, 1].reshape(ii.shape).astype(np.float32)
    back = cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    inside = cv2.remap(np.full((H, W), 255, np.uint8), mapx, mapy, cv2.INTER_NEAREST, borderValue=0) > 0
    crop = ref[y0:y1, x0:x1].copy()
    # the reference stays as it is, a little paler; what is drawn on the map put back (its roads, lines and
    # labels, measured as distance from its ground colour) is laid on top in magenta. Where they line up, the
    # magenta falls exactly on the reference's own features; a misfit shows as magenta beside them
    t = ink(back).astype(np.float32)[..., None] / 255.0  # 1 on the ground, 0 on what is drawn
    t = 1 - 0.8 * (1 - t)  # at most 80% magenta, so the reference stays visible under it
    layer = t * 255.0 + (1 - t) * np.array(MAGENTA, np.float32)
    base = cv2.addWeighted(crop, 0.6, np.full_like(crop, 255), 0.4, 0).astype(np.float32)
    over = (base * layer / 255.0).astype(np.uint8)
    crop[inside] = over[inside]
    pts = np.round(fp - [x0, y0]).astype(np.int32)
    cv2.polylines(crop, [pts], True, (0, 0, 255), 2)
    cv2.imwrite(str(out) + "-magenta.jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(json.dumps({"input": str(out) + "-input.jpg", "result": str(out) + "-magenta.jpg", "gcps": len(cr)}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
