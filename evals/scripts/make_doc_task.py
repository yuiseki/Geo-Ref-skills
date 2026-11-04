"""Put a task's map into documents, for level 5: find the map in a document, then georeference it.

    python scripts/make_doc_task.py tmp/t/task/image.png --out tmp/t/doc --seed 1

Writes, for one A4 page:
    page.png      the page drawn at --dpi: body text, a bar chart and the map at a random place and size
    scan.pdf      that page as one image (a scanned document)
    embedded.pdf  the page without the map as one image, and the map as its own image object on top
    placement.json  the map's rectangle on the page in points from the top left (map_pt: left, top, width,
                  height), the page size, the dpi and the seed
crop_truth() turns the task's truth into the truth of any crop of the page drawn at any dpi, so an answer
for a crop is scored against the right transform.
"""

import argparse
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


def make_documents(map_path, out, seed=0, dpi=150):
    from PIL import Image, ImageDraw
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    m = Image.open(map_path).convert("RGB")
    W, H = m.size
    s = dpi / 72.0
    pw, ph = int(round(A4[0] * s)), int(round(A4[1] * s))
    width_pt = float(rng.uniform(300, 500))
    height_pt = width_pt * H / W
    left = float(rng.uniform(40, A4[0] - 40 - width_pt))
    top = float(rng.uniform(260, A4[1] - 140 - height_pt))
    background = Image.new("RGB", (pw, ph), (255, 255, 255))
    _filler(ImageDraw.Draw(background), pw, ph, rng, s)
    page = background.copy()
    box = [int(round(left * s)), int(round(top * s)), int(round((left + width_pt) * s)), int(round((top + height_pt) * s))]
    page.paste(m.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS), box[:2])
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
    pl = {"map_pt": [left, top, width_pt, height_pt], "page_size_pt": list(A4), "dpi": dpi, "seed": seed,
          "map_px": [W, H]}
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
