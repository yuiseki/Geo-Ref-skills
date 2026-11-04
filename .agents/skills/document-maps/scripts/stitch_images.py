"""Put back together a picture that the PDF stores as several tiles or strips.

    python scripts/stitch_images.py tmp/doc/images/manifest.json

Many PDF producers cut a large raster (a scanned map, a big photograph) into strips or a grid of tiles, each its
own image object. Taken one by one, no tile holds enough of the map to place it. Images on the same page are
joined when they touch edge to edge (gap under 0.5 pt plus 1.5 px), have the same resolution (within 2 % on
each axis), and run along the shared edge together (90 % of the shorter edge). Each group of two or more is
kept only when its pieces fill their union rectangle (within 2 %), and is pasted into one PNG at the tiles'
resolution.

Writes p{page}-s{n}.png next to the tiles and adds "stitched": [{id, file, px, page, page_size_pt, bbox_pt,
parts: [image ids]}] to manifest.json. The tiles stay in "images": hand on the stitched picture first, then
the tiles, and let the gates decide. Images inside Form XObjects (no bbox_pt) are not joined.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image


def _scale(im):
    x0, y0, x1, y1 = im["bbox_pt"]
    return im["px"][0] / (x1 - x0), im["px"][1] / (y1 - y0)


def _close(a, b, tol=0.02):
    return abs(a - b) <= tol * max(a, b)


def _touch(a, b):
    sa, sb = _scale(a), _scale(b)
    if not (_close(sa[0], sb[0]) and _close(sa[1], sb[1])):
        return False
    ax0, ay0, ax1, ay1 = a["bbox_pt"]
    bx0, by0, bx1, by1 = b["bbox_pt"]
    gx = 0.5 + 1.5 / min(sa[0], sb[0])
    gy = 0.5 + 1.5 / min(sa[1], sb[1])
    run = lambda lo0, hi0, lo1, hi1: max(0.0, min(hi0, hi1) - max(lo0, lo1)) >= 0.9 * min(hi0 - lo0, hi1 - lo1)
    side = (abs(ax1 - bx0) <= gx or abs(bx1 - ax0) <= gx) and run(ay0, ay1, by0, by1)
    stack = (abs(ay1 - by0) <= gy or abs(by1 - ay0) <= gy) and run(ax0, ax1, bx0, bx1)
    return side or stack


def _groups(imgs):
    parent = list(range(len(imgs)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(imgs)):
        for j in range(i + 1, len(imgs)):
            if _touch(imgs[i], imgs[j]):
                parent[root(i)] = root(j)
    out = {}
    for i in range(len(imgs)):
        out.setdefault(root(i), []).append(imgs[i])
    return [g for g in out.values() if len(g) > 1]


def stitch(manifest, folder):
    folder = Path(folder)
    out = []
    by_page = {}
    for im in manifest["images"]:
        if "bbox_pt" in im and "page" in im:
            by_page.setdefault(im["page"], []).append(im)
    for page, imgs in sorted(by_page.items()):
        for g in _groups(imgs):
            ux0 = min(i["bbox_pt"][0] for i in g)
            uy0 = min(i["bbox_pt"][1] for i in g)
            ux1 = max(i["bbox_pt"][2] for i in g)
            uy1 = max(i["bbox_pt"][3] for i in g)
            area = sum((i["bbox_pt"][2] - i["bbox_pt"][0]) * (i["bbox_pt"][3] - i["bbox_pt"][1]) for i in g)
            if not _close(area, (ux1 - ux0) * (uy1 - uy0)):
                continue
            sx = sum(_scale(i)[0] for i in g) / len(g)
            sy = sum(_scale(i)[1] for i in g) / len(g)
            W, H = round((ux1 - ux0) * sx), round((uy1 - uy0) * sy)
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            for i in g:
                tile = Image.open(folder / i["file"]).convert("RGB")
                canvas.paste(tile, (round((i["bbox_pt"][0] - ux0) * sx), round((uy1 - i["bbox_pt"][3]) * sy)))
            n = len(out) + 1
            name = f"p{page:03d}-s{n:03d}.png"
            canvas.save(folder / name)
            out.append({"id": f"s{n}", "file": name, "px": [W, H], "page": page,
                        "page_size_pt": g[0].get("page_size_pt"),
                        "bbox_pt": [round(ux0, 3), round(uy0, 3), round(ux1, 3), round(uy1, 3)],
                        "parts": sorted(i["id"] for i in g)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    a = ap.parse_args()
    path = Path(a.manifest)
    man = json.loads(path.read_text(encoding="utf-8"))
    man["stitched"] = stitch(man, path.parent)
    path.write_text(json.dumps(man, indent=2), encoding="utf-8")
    print(json.dumps({"stitched": len(man["stitched"])}))
    sys.exit(0)


if __name__ == "__main__":
    main()
