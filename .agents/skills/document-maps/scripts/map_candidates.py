"""Every place in a document or picture that may hold a map, as crops in the order to try them.

    python scripts/map_candidates.py report.pdf --out tmp/doc/cands [--render-dpi 150] [--per-page 3]
    python scripts/map_candidates.py poster.jpg --out tmp/doc/cands

One command over the other tools of this skill. Candidates come from:
    image / stitched  image objects that are part of a page, tiles joined back first (stitch_images)
    rectangle         map-like rectangles (find_map_rectangles, best --per-page) inside each image that covers
                      90 % of its page or more (a scanned page, a page background)
    rendered          PDF only: map-like rectangles on each page drawn at --render-dpi, for maps drawn as
                      vectors; pages covered by a page-sized image are not drawn again, and a rectangle that is
                      an image object already listed is dropped in favour of the image (its own pixels)
All of them are ordered by one rank: how map-like the crop looks (find_map_rectangles.appearance: fill,
orientations, colours, palette) times its share of the page, full weight from a quarter of the page up. On
Wikimedia Commons PDFs most maps are vector drawings, and the image objects are logos, photographs, insets and
pieces of the map, so no source is put first by kind. Last come the page-sized images whole, and for a picture
(png, jpg, tif, ...) the picture whole.

Nothing is thrown away for looking unlike a map. Hand the crops on in this order and stop at the first one the
georeferencing accepts; a crop that is not a map fails to register and the gates say so.

Writes cand-NNN.png and candidates.json: source (path, sha256), and candidates [{file, px, page, dpi,
bbox_pt (PDF points, origin bottom left), score (rectangles), from: {kind, image, box_px}}]. dpi and bbox_pt
are left out where unknown (Office media, pictures, images inside Form XObjects).
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import extract_images  # noqa: E402
import find_map_rectangles  # noqa: E402
import stitch_images  # noqa: E402

PICTURE = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


def _page_sized(im):
    if "bbox_pt" not in im or not im.get("page_size_pt"):
        return False
    x0, y0, x1, y1 = im["bbox_pt"]
    w, h = im["page_size_pt"]
    return (x1 - x0) * (y1 - y0) >= 0.9 * w * h


def _dpi(im):
    if "bbox_pt" not in im:
        return None
    x0, _, x1, _ = im["bbox_pt"]
    return im["px"][0] * 72.0 / (x1 - x0)


def _rect_pt(im_bbox, im_px, box):
    """Box in image pixels (corner convention, rows down) to PDF points of the page."""
    x0, y0, x1, y1 = im_bbox
    sx, sy = (x1 - x0) / im_px[0], (y1 - y0) / im_px[1]
    return [round(x0 + box[0] * sx, 3), round(y1 - box[3] * sy, 3), round(x0 + box[2] * sx, 3), round(y1 - box[1] * sy, 3)]


def _share(bbox_pt, page_size_pt):
    x0, y0, x1, y1 = bbox_pt
    return (x1 - x0) * (y1 - y0) / float(page_size_pt[0] * page_size_pt[1])


def rank(score, share, full=0.25):
    """A map in a document is usually a large part of its page: the look score, times the share of the page,
    full weight from a quarter of the page up."""
    return score * min(1.0, share / full)


def _iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / float(area(a) + area(b) - inter)


def collect(src, out, render_dpi=150, per_page=3, min_px=64):
    src, out = Path(src), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ranked, last = [], []  # (rank, record, pixels) to sort; whole pages and pictures, kept for the end

    def rects_of(img, base, page_size_pt=None):
        for r in find_map_rectangles.find(img)[:per_page]:
            x0, y0, x1, y1 = r["box"]
            rec = {**{k: v for k, v in base.items() if k != "from"}, "score": round(r["score"], 4),
                   "from": {**base["from"], "box_px": [x0, y0, x1, y1]}}
            if "bbox_pt" in base:
                rec["bbox_pt"] = _rect_pt(base["bbox_pt"], [img.shape[1], img.shape[0]], r["box"])
                share = _share(rec["bbox_pt"], page_size_pt)
            else:
                share = (x1 - x0) * (y1 - y0) / float(img.shape[0] * img.shape[1])
            ranked.append((rank(r["score"], share), rec, img[y0:y1, x0:x1]))

    if src.suffix.lower() in PICTURE:
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(src)
        rects_of(img, {"from": {"kind": "rectangle", "image": src.name}})
        last.append(({"from": {"kind": "image", "image": src.name, "box_px": [0, 0, img.shape[1], img.shape[0]]}},
                     src if src.suffix.lower() == ".png" else img))
    else:
        ex = out / "extract"
        man = extract_images.extract(src, ex)
        man["stitched"] = stitch_images.stitch(man, ex)
        (ex / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
        pics = [dict(s, kind="stitched") for s in man["stitched"]] + [dict(i, kind="image") for i in man["images"]]
        pics = [p for p in pics if min(p["px"]) >= min_px]
        pages = [p for p in pics if _page_sized(p)]
        for p in pics:
            if _page_sized(p):
                continue
            img = cv2.imread(str(ex / p["file"]), cv2.IMREAD_COLOR)
            if img is None:
                continue
            rec = {"from": {"kind": p["kind"], "image": p["file"], "box_px": [0, 0, *p["px"]]}}
            for k in ("page", "bbox_pt"):
                if k in p:
                    rec[k] = p[k]
            if _dpi(p):
                rec["dpi"] = round(_dpi(p), 3)
            sc, _ = find_map_rectangles.appearance(img)
            rec["score"] = round(sc, 4)
            share = _share(p["bbox_pt"], p["page_size_pt"]) if "bbox_pt" in p and p.get("page_size_pt") else 0.0
            ranked.append((rank(sc, share), rec, ex / p["file"]))
        for p in pages:
            img = cv2.imread(str(ex / p["file"]), cv2.IMREAD_COLOR)
            base = {"page": p["page"], "dpi": round(_dpi(p), 3), "bbox_pt": p["bbox_pt"],
                    "from": {"kind": "rectangle", "image": p["file"]}}
            rects_of(img, base, p["page_size_pt"])
            last.append(({**base, "from": {"kind": "image", "image": p["file"], "box_px": [0, 0, *p["px"]]}},
                         ex / p["file"]))
        if src.suffix.lower() == ".pdf":
            import render_pages
            covered = {p["page"] for p in pages}
            rp = render_pages.render(src, out / "pages", dpi=render_dpi)
            for pg in rp["pages"]:
                if pg["page"] in covered:
                    continue
                img = cv2.imread(str(out / "pages" / pg["file"]), cv2.IMREAD_COLOR)
                w, h = pg["page_size_pt"]
                n0 = len(ranked)
                rects_of(img, {"page": pg["page"], "dpi": render_dpi, "bbox_pt": [0, 0, w, h],
                               "from": {"kind": "rendered", "image": f"pages/{pg['file']}"}}, [w, h])
                # a drawn rectangle that is an image object already listed: keep the image (its own pixels)
                for k in range(len(ranked) - 1, n0 - 1, -1):
                    rr, rec, _ = ranked[k]
                    for m in range(n0):
                        r2, rec2, px2 = ranked[m]
                        if rec2.get("page") == rec["page"] and "bbox_pt" in rec2 and _iou(rec2["bbox_pt"], rec["bbox_pt"]) > 0.9:
                            ranked[m] = (max(r2, rr), rec2, px2)
                            del ranked[k]
                            break
    cands = []
    for _, rec, px in sorted(ranked, key=lambda t: -t[0]) + [(None, r, p) for r, p in last]:
        rec["file"] = f"cand-{len(cands) + 1:03d}.png"
        if isinstance(px, Path):
            shutil.copyfile(px, out / rec["file"])
            h, w = cv2.imread(str(px), cv2.IMREAD_UNCHANGED).shape[:2]
        else:
            cv2.imwrite(str(out / rec["file"]), px)
            h, w = px.shape[:2]
        rec["px"] = [w, h]
        cands.append(rec)
    res = {"source": {"path": str(src), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()},
           "tool": "document-maps/map_candidates.py", "candidates": cands}
    (out / "candidates.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--render-dpi", type=float, default=150)
    ap.add_argument("--per-page", type=int, default=3)
    a = ap.parse_args()
    res = collect(a.src, a.out, a.render_dpi, a.per_page)
    print(json.dumps({"candidates": len(res["candidates"]), "out": a.out}))
    sys.exit(0)


if __name__ == "__main__":
    main()
