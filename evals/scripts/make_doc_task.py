"""Put a task's map into documents, for level 5: find the map in a document, then georeference it.

    python scripts/make_doc_task.py tmp/t/task/image.png --out tmp/t/doc --seed 1

Writes, for one A4 page:
    page.png      the page drawn at --dpi: body text, a bar chart and the map at a random place and size
    scan.pdf      that page as one image (a scanned document)
    embedded.pdf  the page without the map as one image, and the map as its own image object on top
    tiled.pdf     as embedded, with the map cut into 3 to 6 horizontal strips, one image object each
    paper.pdf     as scan, on yellowish paper with sensor noise and JPEG (no skew, so the placement holds)
    placement.json  the map's rectangle on the page in points from the top left (map_pt: left, top, width,
                  height), the page size, the dpi and the seed
crop_truth() turns the task's truth into the truth of any crop of the page drawn at any dpi, so an answer
for a crop is scored against the right transform.
"""

import argparse
import io
import json
from pathlib import Path

import numpy as np

A4 = (595.0, 842.0)


def _filler(draw, W, H, rng, scale):
    for i in range(int(rng.integers(8, 16))):
        y = int((60 + i * 14) * scale)
        x = int(50 * scale)
        while x < W - 60 * scale:
            ln = int(rng.integers(3, 9) * 5 * scale)
            draw.rectangle([x, y, x + ln, y + int(6 * scale)], fill=(50, 50, 50))
            x += ln + int(5 * scale)
    base = int(H - 80 * scale)
    for i in range(int(rng.integers(3, 7))):
        hgt = int(rng.integers(30, 120) * scale)
        x = int((80 + i * 40) * scale)
        draw.rectangle([x, base - hgt, x + int(28 * scale), base], fill=(70, 110, 170))


def _photo(w, h, rng):
    """Smooth shading and sensor noise, the look of a photograph."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 3), np.float32)
    for c in range(3):
        for _ in range(4):
            cx, cy, sg = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.1, 0.4) * max(w, h)
            img[..., c] += rng.uniform(40, 120) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sg * sg))
    img += rng.normal(0, 10, img.shape)
    return np.clip(img + 40, 0, 235).astype(np.uint8)


def make_documents(map_path, out, seed=0, dpi=150, layout="plain"):
    """layout plain: the map across the page among text and a chart. layout report: the map in one column with a
    photograph of about its size in the other, a caption just under the map, and on the printed page (scan,
    paper) a legend box over the map's lower corner, as reports print them."""
    from PIL import Image, ImageDraw
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    m = Image.open(map_path).convert("RGB")
    W, H = m.size
    s = dpi / 72.0
    pw, ph = int(round(A4[0] * s)), int(round(A4[1] * s))
    if layout == "report":
        width_pt = float(rng.uniform(230, 265))
        height_pt = min(width_pt * H / W, 330.0)
        width_pt = height_pt * W / H
        on_left = bool(rng.random() < 0.5)
        left = 40.0 if on_left else A4[0] - 40 - width_pt
        top = float(rng.uniform(290, A4[1] - 160 - height_pt))
    else:
        width_pt = float(rng.uniform(300, 500))
        height_pt = width_pt * H / W
        left = float(rng.uniform(40, A4[0] - 40 - width_pt))
        top = float(rng.uniform(260, A4[1] - 140 - height_pt))
    background = Image.new("RGB", (pw, ph), (255, 255, 255))
    draw = ImageDraw.Draw(background)
    _filler(draw, pw, ph, rng, s)
    box = [int(round(left * s)), int(round(top * s)), int(round((left + width_pt) * s)), int(round((top + height_pt) * s))]
    if layout == "report":
        draw.rectangle([0, box[1] - int(10 * s), pw, ph], fill=(255, 255, 255))  # the column row starts clean
        pw_pt = float(rng.uniform(200, 240))
        ph_pt = pw_pt * float(rng.uniform(0.6, 0.9))
        px0 = int(round((A4[0] - 40 - pw_pt if on_left else 40) * s))
        py0 = int(round((top + rng.uniform(-10, 30)) * s))
        photo = _photo(int(pw_pt * s), int(ph_pt * s), rng)
        background.paste(Image.fromarray(photo), (px0, py0))
        cap_w = int((box[2] - box[0]) * rng.uniform(0.6, 0.9))
        cy = box[3] + int(4 * s)
        draw.rectangle([box[0], cy, box[0] + cap_w, cy + int(7 * s)], fill=(50, 50, 50))
    page = background.copy()
    page.paste(m.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS), box[:2])
    if layout == "report":
        lw, lh = int((box[2] - box[0]) * rng.uniform(0.2, 0.3)), int((box[3] - box[1]) * rng.uniform(0.15, 0.25))
        lx0, ly0 = box[2] - lw - int(4 * s), box[3] - lh - int(4 * s)
        pd = ImageDraw.Draw(page)
        pd.rectangle([lx0, ly0, lx0 + lw, ly0 + lh], fill=(255, 255, 255), outline=(0, 0, 0), width=max(1, int(s)))
        for k in range(3):
            yy = ly0 + int((k + 0.5) * lh / 3) - int(3 * s)
            pd.rectangle([lx0 + int(5 * s), yy, lx0 + int(13 * s), yy + int(6 * s)],
                         fill=[(220, 80, 60), (70, 130, 200), (90, 170, 90)][k])
            pd.rectangle([lx0 + int(17 * s), yy + int(1 * s), lx0 + lw - int(6 * s), yy + int(5 * s)], fill=(60, 60, 60))
    page.save(out / "page.png")
    page.save(out / "scan.pdf", resolution=dpi)
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(*A4)
    for im, (x, y, w, h) in ((background, (0, 0, A4[0], A4[1])),
                             (m, (left, A4[1] - top - height_pt, width_pt, height_pt))):
        obj = pdfium.PdfImage.new(doc)
        obj.set_bitmap(pdfium.PdfBitmap.from_pil(im))
        obj.set_matrix(pdfium.PdfMatrix().scale(w, h).translate(x, y))
        pg.insert_obj(obj)
    pg.gen_content()
    doc.save(str(out / "embedded.pdf"))
    # tiled: the map cut into horizontal strips, each its own image object, as many PDF producers store rasters
    n = int(rng.integers(3, 7))
    rows = [round(H * k / n) for k in range(n + 1)]
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(*A4)
    parts = [(background, (0, 0, A4[0], A4[1]))]
    for r0, r1 in zip(rows[:-1], rows[1:]):
        y_top = top + height_pt * r0 / H
        parts.append((m.crop((0, r0, W, r1)), (left, A4[1] - y_top - height_pt * (r1 - r0) / H, width_pt,
                                               height_pt * (r1 - r0) / H)))
    for im, (x, y, w, h) in parts:
        obj = pdfium.PdfImage.new(doc)
        obj.set_bitmap(pdfium.PdfBitmap.from_pil(im))
        obj.set_matrix(pdfium.PdfMatrix().scale(w, h).translate(x, y))
        pg.insert_obj(obj)
    pg.gen_content()
    doc.save(str(out / "tiled.pdf"))
    # paper: the scan on yellowish paper, with sensor noise and JPEG, still axis-aligned so the truth holds
    tint = np.array((238, 234, 226), np.float32) / 255.0
    arr = np.asarray(page).astype(np.float32) * tint + rng.normal(0, 4, (ph, pw, 3))
    scan = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    scan.save(buf, format="JPEG", quality=75)
    Image.open(buf).save(out / "paper.pdf", resolution=dpi)
    pl = {"map_pt": [left, top, width_pt, height_pt], "page_size_pt": list(A4), "dpi": dpi, "seed": seed,
          "map_px": [W, H], "layout": layout}
    (out / "placement.json").write_text(json.dumps(pl, indent=2), encoding="utf-8")
    return pl


def crop_truth(truth, placement, box, dpi):
    """Truth for the crop box (x0, y0, x1, y1, page pixels at dpi, corner convention) of the page drawn at dpi:
    crop px -> page pt -> task px -> the task's global px."""
    left, top, w, h = placement["map_pt"]
    W, H = truth["width"], truth["height"]
    k = 72.0 / dpi
    sx, sy = k * W / w, k * H / h
    C = np.array([[sx, 0, (box[0] * k - left) * W / w], [0, sy, (box[1] * k - top) * H / h], [0, 0, 1.0]])
    D = np.asarray(truth["task_px_to_global_px"]) @ C
    return {**truth, "width": int(round(box[2] - box[0])), "height": int(round(box[3] - box[1])),
            "task_px_to_global_px": D.tolist(), "crop": {"box": list(map(float, box)), "dpi": dpi}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dpi", type=float, default=150)
    a = ap.parse_args()
    print(json.dumps(make_documents(a.map, a.out, a.seed, a.dpi)))


if __name__ == "__main__":
    main()
