"""Rectangles on a rendered page that may hold a map, ranked, none thrown away for looking unlike a map.

    python scripts/find_map_rectangles.py tmp/doc/pages/p001.png --out tmp/doc/cands [--min-area 0.02]

Candidates come from two cues, both classical:
    regions  content on the paper, closed over small gaps, as connected blocks. The paper's colour and noise
             are measured on the page's outer margin, so a scan on off-white paper works like a white page
    cores    with blank areas enclosed by the region filled in (a legend box on the map), the largest
             rectangle of 16 px blocks at least half filled (lone empty
             blocks closed) inside each region, its sides then
             moved to the last mostly-filled row or column (a chart, a caption or a
             legend touching the map widens its region but not this rectangle)
    cuts     the blocks a region splits into along blank gutters running right through it (XY-cut), for
             panels of maps set close together
    frames   long, thin (under 0.6 % of the page width) horizontal and vertical lines (a map's neat line) and the rectangles they enclose
Boxes overlapping more than 80 % are one candidate. Each gets features and a ranking score:
    fill          share of the box that is not paper (a map is drawn all over; a paragraph is mostly paper)
    colours       number of distinct colours (quantised to 8 levels a channel) covering 0.2 % of the box or more
    orientations  entropy of gradient directions, 0..1 (a map's lines run every way; text and tables run two)
    palette       share of the box covered by its 8 commonest colours (after a 3x3 median, 8 levels a channel).
                  A map is a few flat fills; a photograph spreads over many shades (maps 0.77-1.0 and
                  photographs 0.36-0.44 on the synthetic and tile pictures it was set on)
    gaps          share of rows with almost no ink (under 0.5 %) against the box's own commonest colour. Lines of
                  text and tables leave blank rows between them, on white or on a coloured panel; a map does not
                  (maps 0.0-0.18, text pages and tables 0.38-0.81 on Wikimedia Commons PDFs)
    score         fill * orientations * min(1, colours / 8) * palette * (1 - gaps)
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
    dom = np.bincount(qm[:, 0] * 64 + qm[:, 1] * 8 + qm[:, 2]).argmax()
    ink = ((qm[:, 0] * 64 + qm[:, 1] * 8 + qm[:, 2]) != dom).reshape(crop.shape[:2])
    gaps = float((ink.mean(axis=1) < 0.005).mean())
    return {"fill": fill, "colours": colours, "orientations": ent, "palette": palette, "gaps": gaps}


def _score(f):
    return f["fill"] * f["orientations"] * min(1.0, f["colours"] / 8.0) * f["palette"] * (1.0 - f["gaps"])


def appearance(crop, colour=(255, 255, 255), noise=0.0):
    """(score, features) of any crop, on paper of the given colour (white by default)."""
    f = _features(crop, np.asarray(colour, np.float32), noise)
    return _score(f), f


def largest_filled_rectangle(mask):
    """(x0, y0, x1, y1) of the largest axis-aligned rectangle of True cells, or None (histogram method)."""
    H, W = mask.shape
    heights = np.zeros(W + 1, np.int64)
    best, box = 0, None
    for y in range(H):
        heights[:W] = np.where(mask[y], heights[:W] + 1, 0)
        stack = []
        for x in range(W + 1):
            h = heights[x]
            start = x
            while stack and stack[-1][1] >= h:
                sx, sh = stack.pop()
                if sh * (x - sx) > best:
                    best, box = int(sh * (x - sx)), (int(sx), int(y - sh + 1), int(x), int(y + 1))
                start = sx
            stack.append((start, h))
    return box


def xy_cut(mask, min_gap=3, max_frac=0.01, min_side=32):
    """Boxes (x0, y0, x1, y1) of the blocks that blank gutters (rows or columns, min_gap wide, with under
    max_frac content, running right through) split mask into, recursively; [] when there is no gutter."""
    def runs(prof):
        blank = prof <= max_frac
        out, start = [], None
        for i, b in enumerate(np.append(blank, False)):
            if b and start is None:
                start = i
            elif not b and start is not None:
                out.append((start, i))
                start = None
        return out

    def trim(x0, y0, x1, y1):
        sub = mask[y0:y1, x0:x1]
        ys, xs = np.where(sub.any(axis=1))[0], np.where(sub.any(axis=0))[0]
        if not len(ys) or not len(xs):
            return None
        return x0 + int(xs[0]), y0 + int(ys[0]), x0 + int(xs[-1]) + 1, y0 + int(ys[-1]) + 1

    def cut(box, depth):
        x0, y0, x1, y1 = box
        sub = mask[y0:y1, x0:x1]
        for axis in (0, 1):  # 0: gutters are columns, 1: rows
            prof = sub.mean(axis=axis)
            gaps = [(a, b) for a, b in runs(prof) if b - a >= min_gap and a > 0 and b < len(prof)]
            if not gaps or depth > 6:
                continue
            edges = [0] + [v for a, b in gaps for v in (a, b)] + [len(prof)]
            leaves = []
            for a, b in zip(edges[::2], edges[1::2]):
                child = trim(x0 + a, y0, x0 + b, y1) if axis == 0 else trim(x0, y0 + a, x1, y0 + b)
                if child and min(child[2] - child[0], child[3] - child[1]) >= min_side:
                    leaves += cut(child, depth + 1) or [child]
            return leaves
        return []

    t = trim(0, 0, mask.shape[1], mask.shape[0])
    return cut(t, 0) if t else []


def fill_holes(mask):
    """mask with every blank area that it encloses filled in (a legend box or a white lake inside a map)."""
    m = np.pad(mask.astype(np.uint8), 1)
    seen = m.copy()
    ff = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    cv2.floodFill(seen, ff, (0, 0), 2)
    return (seen != 2)[1:-1, 1:-1]


def _refine(mask, box, step, frac=0.5):
    """Move each side of a block-aligned box to the pixel where the row or column stops being mostly content."""
    x0, y0, x1, y1 = box
    H, W = mask.shape
    full = lambda a: a.size and a.mean() >= frac
    for _ in range(step):
        if y0 > 0 and full(mask[y0 - 1, x0:x1]):
            y0 -= 1
        if y1 < H and full(mask[y1, x0:x1]):
            y1 += 1
        if x0 > 0 and full(mask[y0:y1, x0 - 1]):
            x0 -= 1
        if x1 < W and full(mask[y0:y1, x1]):
            x1 += 1
    return int(x0), int(y0), int(x1), int(y1)


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
    k = max(3, int(close_frac * W)) | 1
    closed = cv2.morphologyEx(content, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    raw = content.astype(bool)
    f = 16  # the core is searched on 16 x 16 blocks at least half filled, so white roads do not cut it
    for i in range(1, n):
        x, y, w, h = stats[i, :4]
        boxes.append(((int(x), int(y), int(x + w), int(y + h)), "region"))
        if w * h < min_area * W * H:
            continue
        comp = fill_holes((labels[y:y + h, x:x + w] == i) & raw[y:y + h, x:x + w])
        hb, wb = h // f, w // f
        if hb == 0 or wb == 0:
            continue
        blocks = (comp[:hb * f, :wb * f].reshape(hb, f, wb, f).mean(axis=(1, 3)) >= 0.5).astype(np.uint8)
        blocks = cv2.morphologyEx(blocks, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)  # lone empty blocks
        r = largest_filled_rectangle(blocks)
        if r:
            box = _refine(raw, (x + r[0] * f, y + r[1] * f, x + r[2] * f, y + r[3] * f), f)
            boxes.append((box, "core"))
        for cx0, cy0, cx1, cy1 in xy_cut(raw[y:y + h, x:x + w] & (labels[y:y + h, x:x + w] == i)):
            boxes.append(((int(x + cx0), int(y + cy0), int(x + cx1), int(y + cy1)), "cut"))
    L = max(10, int(line_frac * W)) | 1  # odd: an even kernel shifts an opening by one pixel
    dark = (cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) < 128).astype(np.uint8)
    t = max(5, int(0.006 * W)) | 1  # a neat line is thinner than this; a dark area is not a line
    hl = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    hl &= 1 - cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, t)))
    vl = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    vl &= 1 - cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (t, 1)))
    lines = cv2.dilate(hl | vl, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(lines, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= L and h >= L:
            boxes.append(((int(x), int(y), int(x + w), int(y + h)), "frame"))
    floor = min_area * W * H
    out = []
    order = {"frame": 0, "core": 1, "cut": 2, "region": 3}
    for box, kind in sorted(boxes, key=lambda b: order[b[1]]):  # frames first, then cores, so they win a merge
        x0, y0, x1, y1 = box
        if (x1 - x0) * (y1 - y0) < floor:
            continue
        if any(_iou(box, c["box"]) > 0.8 for c in out):
            continue
        f = _features(page[y0:y1, x0:x1], colour, noise)
        score = _score(f)
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
