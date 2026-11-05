"""Pictures of road access maps: a map warped to a reference map by its answer, and a time series of road GeoJSON
files as an animated GIF on one reference map.

    uvx --with numpy --with opencv-python-headless --with pypdfium2 --with pillow python scripts/road_render.py georef \
        --pdf map.pdf --run work/runs/<stem> --results work/results.jsonl --reference ref_dir --out map_georef.jpg
    uvx --with numpy --with opencv-python-headless --with pillow python scripts/road_render.py gif \
        a.geojson b.geojson ... --reference ref_dir --out series.gif [--width 800] [--ms 700]

ref_dir holds reference.png and reference.json (EPSG:3857, its geotransform; tile-reference makes one). georef
renders the page at the panel's dpi, cuts the panel, and pulls every reference pixel back into it through the
inverse of the answer (an affine or projective fit from mercator to the panel's pixels); the table beside the map and
the insets (road_geojson's cut, the same boxes) are left out, so what is drawn is only what the answer places. gif
draws each date's roads in the status colours, captioned with the date and the length of road in each status.
"""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

import transforms as tf
import webmercator as wm

COLOURS = {"passable": (0, 170, 0), "passable with difficulties": (255, 165, 0), "not passable": (220, 0, 0),
           "last-mile delivery by land cruiser": (230, 0, 200)}
LABELS = {"passable": "Passable", "passable with difficulties": "Passable with difficulties",
          "not passable": "Not passable", "last-mile delivery by land cruiser": "Land cruiser only"}
CREDIT = ("Roads: derived automatically from WFP Logistics Cluster maps, (c) Logistics Cluster / WFP. No warranty.",
          "Basemap: (c) OpenStreetMap contributors, OpenMapTiles.")


def warp(panel, method, src, dst, gt, size, masks):
    """The panel (H x W x 3) pulled into a reference of size (w, h) with geotransform gt, through the fit from dst
    (mercator) to src (panel pixels); masks are panel-pixel boxes left out. Returns the image and its alpha (0/1)."""
    w, h = size
    inv = tf.fit(method, np.asarray(dst, float), np.asarray(src, float))
    u, v = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    mx, my = gt[0] + u * gt[1], gt[3] + v * gt[5]
    cr = inv.predict(np.stack([mx.ravel(), my.ravel()], axis=1))
    mapx = cr[:, 0].reshape(h, w).astype(np.float32)
    mapy = cr[:, 1].reshape(h, w).astype(np.float32)
    H, W = panel.shape[:2]
    keep = (mapx >= 0) & (mapx < W) & (mapy >= 0) & (mapy < H)
    for b in masks:
        keep &= ~((mapx >= b[0]) & (mapx <= b[2]) & (mapy >= b[1]) & (mapy <= b[3]))
    out = cv2.remap(panel, mapx - 0.5, mapy - 0.5, cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT)
    return out, keep.astype(np.uint8)


def km_of(geometry):
    parts = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
    total = 0.0
    for p in parts:
        for (a, b), (c, d) in zip(p, p[1:]):
            la, lc = math.radians(b), math.radians(d)
            x = math.radians(c - a) * math.cos((la + lc) / 2)
            total += 6371.0 * math.hypot(x, lc - la)
    return total


def frames_of(docs):
    """(date, features, km by status) in date order, one per date."""
    seen, out = set(), []
    for doc in sorted(docs, key=lambda d: d.get("map_date") or ""):
        d = doc.get("map_date")
        if d in seen:
            continue
        seen.add(d)
        km = {}
        for f in doc["features"]:
            s = f["properties"]["status"]
            km[s] = km.get(s, 0.0) + km_of(f["geometry"])
        out.append((d, doc["features"], km))
    return out


def to_px(gt, lon, lat):
    mx, my = wm.lonlat_to_mercator(lon, lat)
    return (mx - gt[0]) / gt[1], (my - gt[3]) / gt[5]


def font(size):
    from PIL import ImageFont
    for f in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def draw_roads(base, gt, features, width=4):
    from PIL import ImageDraw
    dr = ImageDraw.Draw(base)
    order = ["passable", "last-mile delivery by land cruiser", "passable with difficulties", "not passable"]
    for s in order:
        for f in features:
            if f["properties"]["status"] != s:
                continue
            g = f["geometry"]
            for p in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                dr.line([to_px(gt, *c) for c in p], fill=COLOURS[s], width=width, joint="curve")
    return base


def legend(img, lines, top_left, size=18):
    """Text lines [(text, colour or None)] in a white box."""
    from PIL import ImageDraw
    dr = ImageDraw.Draw(img)
    f = font(size)
    x, y = top_left
    w = max(dr.textlength(t, font=f) for t, _ in lines) + (34 if any(c for _, c in lines) else 0) + 16
    dr.rectangle([x, y, x + w, y + len(lines) * (size + 8) + 10], fill=(255, 255, 255), outline=(120, 120, 120))
    for i, (t, c) in enumerate(lines):
        yy = y + 8 + i * (size + 8)
        tx = x + 8
        if c:
            dr.line([x + 8, yy + size / 2, x + 34, yy + size / 2], fill=c, width=5)
            tx = x + 42
        dr.text((tx, yy), t, fill=(0, 0, 0), font=f)


def credit(img, size=13):
    from PIL import ImageDraw
    dr = ImageDraw.Draw(img)
    f = font(size)
    h = (size + 4) * len(CREDIT) + 6
    dr.rectangle([0, img.height - h, img.width, img.height], fill=(255, 255, 255))
    for i, t in enumerate(CREDIT):
        dr.text((6, img.height - h + 3 + i * (size + 4)), t, fill=(60, 60, 60), font=f)


def load_reference(ref_dir):
    from PIL import Image
    ref = json.loads((Path(ref_dir) / "reference.json").read_text())
    img = Image.open(Path(ref_dir) / "reference.png").convert("RGB")
    return img, ref["geotransform"]


def faded(img, k=0.45):
    from PIL import Image
    return Image.blend(img, Image.new("RGB", img.size, (255, 255, 255)), k)


def cmd_georef(a):
    import pypdfium2 as pdfium
    from PIL import Image
    import road_access as ra
    import road_geojson as rg
    import pdf_words as pw
    pdf = Path(a.pdf)
    res = next(json.loads(l) for l in open(a.results) if json.loads(l)["file"] == pdf.name)
    P, inner = rg.panel_of(Path(a.run), res)
    page = pdfium.PdfDocument(str(pdf))[0]
    ps = ra.paths(page)
    inner = rg.snap_to_edge(inner + rg.inset_boxes(ra.rectangles(ps), P, P["box"]), P["box"],
                            near=rg.INSET_NEAR_PT * P["k"], pad=rg.INSET_PAD_PT * P["k"])
    rows = ra.table_rows(pw.words(pw.chars(pdf)), [p for p in ps if p["fill"]])
    full = np.array(page.render(scale=P["k"]).to_pil().convert("RGB"))[:, :, ::-1]
    b = [int(round(v)) for v in P["box"]]
    panel = full[max(b[1], 0):b[3], max(b[0], 0):b[2]]
    ox, oy = max(b[0], 0), max(b[1], 0)
    masks = [[q[0] - ox, q[1] - oy, q[2] - ox, q[3] - oy] for q in inner]
    if rows:  # the table beside the map, from its left edge on
        left = min(r["x"] for r in rows) * P["k"] - 6 - ox
        masks.append([left, -1e9, 1e9, 1e9])
    ans_dir = Path(a.run)
    ans = json.loads((ans_dir / f"answer.c{res['cand']}.{res['method']}.json").read_text())
    src = np.array([[q["col"], q["row"]] for q in ans["gcps"]])
    dst = np.array([wm.lonlat_to_mercator(q["lon"], q["lat"]) for q in ans["gcps"]])
    ref, gt = load_reference(a.reference)
    out, alpha = warp(panel, ans["method"], src, dst, gt, ref.size, masks)
    base = np.array(faded(ref, 0.2))[:, :, ::-1].astype(np.float32)
    k = (alpha[:, :, None] * a.opacity).astype(np.float32)
    img = Image.fromarray((base * (1 - k) + out * k).astype(np.uint8)[:, :, ::-1])
    if a.width and img.width > a.width:
        img = img.resize((a.width, round(img.height * a.width / img.width)), Image.LANCZOS)
    credit_lines = ("Map: (c) Logistics Cluster / WFP, warped automatically by its place names. No warranty.",
                    "Basemap: (c) OpenStreetMap contributors, OpenMapTiles.")
    from PIL import ImageDraw
    dr = ImageDraw.Draw(img)
    f = font(13)
    h = 17 * len(credit_lines) + 6
    dr.rectangle([0, img.height - h, img.width, img.height], fill=(255, 255, 255))
    for i, t in enumerate(credit_lines):
        dr.text((6, img.height - h + 3 + i * 17), t, fill=(60, 60, 60), font=f)
    img.save(a.out, quality=85)
    print(json.dumps({"out": a.out, "gcps": len(src), "masks": len(masks)}))


def cmd_gif(a):
    from PIL import Image
    docs = [json.loads(Path(p).read_text()) for p in a.geojson]
    ref, gt = load_reference(a.reference)
    frames = []
    for d, feats, km in frames_of(docs):
        img = draw_roads(faded(ref), gt, feats, width=a.line)
        lines = [(d, None)] + [(f"{LABELS[s]}: {round(km.get(s, 0)):,} km", COLOURS[s])
                               for s in LABELS if s in km or s != "last-mile delivery by land cruiser"]
        if a.width and img.width > a.width:
            img = img.resize((a.width, round(img.height * a.width / img.width)), Image.LANCZOS)
        legend(img, lines, (10, 10), size=max(12, a.width // 50))
        credit(img, size=max(10, a.width // 70))
        frames.append(img.quantize(colors=96, method=Image.MEDIANCUT, dither=Image.NONE))
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=a.ms, loop=0, optimize=True)
    print(json.dumps({"out": a.out, "frames": len(frames)}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("georef")
    g.add_argument("--pdf", required=True)
    g.add_argument("--run", required=True)
    g.add_argument("--results", required=True)
    g.add_argument("--reference", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--opacity", type=float, default=0.85)
    g.add_argument("--width", type=int, default=1000)
    m = sub.add_parser("gif")
    m.add_argument("geojson", nargs="+")
    m.add_argument("--reference", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--width", type=int, default=800)
    m.add_argument("--line", type=int, default=5)
    m.add_argument("--ms", type=int, default=700)
    a = ap.parse_args()
    {"georef": cmd_georef, "gif": cmd_gif}[a.cmd](a)


if __name__ == "__main__":
    main()
