"""Every place in a document or picture that may hold a map, as crops in the order to try them.

    python scripts/map_candidates.py report.pdf --out tmp/doc/cands [--render-dpi 150] [--per-page 3]
    python scripts/map_candidates.py poster.jpg --out tmp/doc/cands

One command over the other tools of this skill. The order:
    1. image objects that are part of a page, largest first, with tiles joined back (stitch_images) and
       the joined picture before its tiles                                               kind image / stitched
    2. inside each image that covers 90 % of its page or more (a scanned page, a page background), the
       map-like rectangles (find_map_rectangles, best --per-page), then that image whole kind rectangle / image
    3. PDF only: each page drawn at --render-dpi, its map-like rectangles, for maps drawn as vectors; pages
       already covered by a page-sized image are not drawn again                         kind rendered
For a picture (png, jpg, tif, ...): its rectangles, then the picture whole.

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


def _rectangles(img, per_page):
    return find_map_rectangles.find(img)[:per_page]


def collect(src, out, render_dpi=150, per_page=3, min_px=64):
    src, out = Path(src), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cands = []

    def add(img_or_path, rec):
        rec["file"] = f"cand-{len(cands) + 1:03d}.png"
        if isinstance(img_or_path, Path):
            shutil.copyfile(img_or_path, out / rec["file"])
            h, w = cv2.imread(str(img_or_path), cv2.IMREAD_UNCHANGED).shape[:2]
        else:
            cv2.imwrite(str(out / rec["file"]), img_or_path)
            h, w = img_or_path.shape[:2]
        rec["px"] = [w, h]
        cands.append(rec)

    def rects_of(img, base):
        for r in _rectangles(img, per_page):
            x0, y0, x1, y1 = r["box"]
            rec = {**{k: v for k, v in base.items() if k != "from"}, "score": round(r["score"], 4),
                   "from": {**base["from"], "box_px": [x0, y0, x1, y1]}}
            if "bbox_pt" in base:
                rec["bbox_pt"] = _rect_pt(base["bbox_pt"], [img.shape[1], img.shape[0]], r["box"])
            add(img[y0:y1, x0:x1], rec)

    if src.suffix.lower() in PICTURE:
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(src)
        rects_of(img, {"from": {"kind": "rectangle", "image": src.name}})
        add(src if src.suffix.lower() == ".png" else img,
            {"from": {"kind": "image", "image": src.name, "box_px": [0, 0, img.shape[1], img.shape[0]]}})
    else:
        ex = out / "extract"
        man = extract_images.extract(src, ex)
        man["stitched"] = stitch_images.stitch(man, ex)
        (ex / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
        pics = [dict(s, kind="stitched") for s in man["stitched"]] + [dict(i, kind="image") for i in man["images"]]
        pics = [p for p in pics if min(p["px"]) >= min_px]
        parts = [p for p in pics if not _page_sized(p)]
        pages = [p for p in pics if _page_sized(p)]
        for p in sorted(parts, key=lambda p: -p["px"][0] * p["px"][1]):
            rec = {"from": {"kind": p["kind"], "image": p["file"], "box_px": [0, 0, *p["px"]]}}
            for k in ("page", "bbox_pt"):
                if k in p:
                    rec[k] = p[k]
            if _dpi(p):
                rec["dpi"] = round(_dpi(p), 3)
            add(ex / p["file"], rec)
        for p in pages:
            img = cv2.imread(str(ex / p["file"]), cv2.IMREAD_COLOR)
            base = {"page": p["page"], "dpi": round(_dpi(p), 3), "bbox_pt": p["bbox_pt"],
                    "from": {"kind": "rectangle", "image": p["file"]}}
            rects_of(img, base)
            add(ex / p["file"], {**base, "from": {"kind": "image", "image": p["file"], "box_px": [0, 0, *p["px"]]}})
        if src.suffix.lower() == ".pdf":
            import render_pages
            covered = {p["page"] for p in pages}
            rp = render_pages.render(src, out / "pages", dpi=render_dpi)
            for pg in rp["pages"]:
                if pg["page"] in covered:
                    continue
                img = cv2.imread(str(out / "pages" / pg["file"]), cv2.IMREAD_COLOR)
                w, h = pg["page_size_pt"]
                rects_of(img, {"page": pg["page"], "dpi": render_dpi, "bbox_pt": [0, 0, w, h],
                               "from": {"kind": "rendered", "image": f"pages/{pg['file']}"}})
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
