"""Rectangles on a rendered page that may hold a map, ranked, none thrown away for looking unlike a map.

    python scripts/find_map_rectangles.py tmp/doc/pages/p001.png --out tmp/doc/cands [--min-area 0.02]

Candidates come from two cues, both classical:
    regions  content on the paper, closed over small gaps, as connected blocks. The paper's colour and noise
             are measured on the page's outer margin, so a scan on off-white paper works like a white page
    frames   long horizontal and vertical lines (a map's neat line) and the rectangles they enclose
Boxes overlapping more than 80 % are one candidate. Each gets features and a ranking score:
    fill          share of the box that is not paper (a map is drawn all over; a paragraph is mostly paper)
    colours       number of distinct colours (quantised to 8 levels a channel) covering 0.2 % of the box or more
    orientations  entropy of gradient directions, 0..1 (a map's lines run every way; text and tables run two)
    palette       share of the box covered by its 8 commonest colours (after a 3x3 median, 8 levels a channel).
                  A map is a few flat fills; a photograph spreads over many shades (maps 0.77-1.0 and
                  photographs 0.36-0.44 on the synthetic and tile pictures it was set on)
    score         fill * orientations * min(1, colours / 8) * palette
The score only orders the candidates. Whether a candidate is a map is decided downstream: a picture that is
not a map does not register against any reference, and the gates say so. Keep every candidate above the size
floor (--min-area, a share of the page), and pass them on in this order.

Writes cand-NN.png crops and candidates.json ({box: [x0, y0, x1, y1] in page pixels, corner convention, kind,
score, features}).
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def paper(page, margin_frac=0.02):
    """Colour (BGR) and noise (grey levels, robust sigma) of the page's outer margin."""
    H, W = page.shape[:2]
    m = max(2, int(margin_frac * min(H, W)))
    border = np.concatenate([page[:m].reshape(-1, 3), page[-m:].reshape(-1, 3),
                             page[:, :m].reshape(-1, 3), page[:, -m:].reshape(-1, 3)]).astype(np.float32)
    colour = np.median(border, axis=0)
    grey = border.mean(axis=1)
    noise = float(1.4826 * np.median(np.abs(grey - np.median(grey))))
    return colour, noise


def content_mask(page, colour, noise):
    """Pixels that differ from the paper by more than the paper's own noise (10 levels at least)."""
    smooth = cv2.medianBlur(page, 3)
    diff = np.abs(smooth.astype(np.int16) - colour.astype(np.int16)).max(axis=2)
    return diff > max(10.0, 5.0 * noise)


def _features(crop, colour, noise):
    fill = float(content_mask(crop, colour, noise).mean())
    m = cv2.medianBlur(crop, 3)
    qm = (m // 32).reshape(-1, 3).astype(np.int32)
    top = np.sort(np.bincount(qm[:, 0] * 64 + qm[:, 1] * 8 + qm[:, 2], minlength=512))[::-1]
    palette = float(top[:8].sum() / len(qm))
    q = (crop // 32).reshape(-1, 3).astype(np.int32)
    codes = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    counts = np.bincount(codes, minlength=512)
    colours = int((counts >= 0.002 * len(codes)).sum())
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    strong = mag > 40
    if strong.sum() < 50:
        ent = 0.0
    else:
        ang = (np.degrees(np.arctan2(gy[strong], gx[strong])) % 180.0)
        h = np.histogram(ang, bins=12, range=(0, 180), weights=mag[strong])[0]
        p = h / h.sum()
        ent = float(-(p[p > 0] * np.log(p[p > 0])).sum() / np.log(12))
    return {"fill": fill, "colours": colours, "orientations": ent, "palette": palette}


def _iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / float(area(a) + area(b) - inter)


def find(page, min_area=0.02, close_frac=0.012, line_frac=0.10):
    H, W = page.shape[:2]
    if page.ndim == 2:
        page = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    colour, noise = paper(page)
    content = content_mask(page, colour, noise).astype(np.uint8)
    boxes = []
    k = max(3, int(close_frac * W))
    closed = cv2.morphologyEx(content, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    for i in range(1, n):
        x, y, w, h = stats[i, :4]
        boxes.append(((int(x), int(y), int(x + w), int(y + h)), "region"))
    L = max(10, int(line_frac * W))
    dark = (cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) < 128).astype(np.uint8)
    hl = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    vl = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    lines = cv2.dilate(hl | vl, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(lines, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= L and h >= L:
            boxes.append(((int(x), int(y), int(x + w), int(y + h)), "frame"))
    floor = min_area * W * H
    out = []
    for box, kind in sorted(boxes, key=lambda b: b[1] != "frame"):  # frames first, so they win a merge
        x0, y0, x1, y1 = box
        if (x1 - x0) * (y1 - y0) < floor:
            continue
        if any(_iou(box, c["box"]) > 0.8 for c in out):
            continue
        f = _features(page[y0:y1, x0:x1], colour, noise)
        score = f["fill"] * f["orientations"] * min(1.0, f["colours"] / 8.0) * f["palette"]
        out.append({"box": [x0, y0, x1, y1], "kind": kind, "score": score, "features": f})
    return sorted(out, key=lambda c: -c["score"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("page")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-area", type=float, default=0.02)
    a = ap.parse_args()
    img = cv2.imread(a.page, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(a.page)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cands = find(img, a.min_area)
    for i, c in enumerate(cands):
        x0, y0, x1, y1 = c["box"]
        c["file"] = f"cand-{i + 1:02d}.png"
        cv2.imwrite(str(out / c["file"]), img[y0:y1, x0:x1])
    (out / "candidates.json").write_text(json.dumps({"page": a.page, "candidates": cands}, indent=2), encoding="utf-8")
    print(json.dumps({"candidates": len(cands), "out": a.out}))
    sys.exit(0)


if __name__ == "__main__":
    main()
