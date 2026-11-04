"""Every raster image embedded in a document, with where it came from.

    python scripts/extract_images.py report.pdf --out tmp/doc/images
    python scripts/extract_images.py slides.pptx --out tmp/doc/images

Writes one PNG per image (or the stored file as it is, for Office documents) and manifest.json:
    source   path, sha256, size of the document
    tool     versions (pypdfium2, pdfium) and this script
    images   [{id, file, px: [w, h], page (1-based) and bbox_pt: [x0, y0, x1, y1] on the page in PDF points
             (origin bottom left of the page as shown: crop box and /Rotate applied, the frame render_pages
             draws) and page_size_pt, for PDF; part (the path inside the zip), for Office}]

PDF (pypdfium2, BSD-3-Clause / Apache-2.0): image objects on each page. An image inside a Form XObject is
reported with "in_form": true and no bbox_pt: pdfium gives its bounds in the form's own space, not the page's
(seen 2026-11-03), and composing the form matrices is not done yet. Office (docx, pptx, xlsx): the files under
word/media, ppt/media and xl/media of the zip, read with the standard library; their place on the page or
slide is not read yet. Old binary formats (doc, ppt, xls) and vector drawings (EMF, WMF, PDF vector maps) are
not images here; render the page instead.

This only finds images. Whether an image is a map is decided later (a map that is not one fails to register
against any reference and the gates say so).
"""

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

OFFICE = {".docx": "word/media/", ".pptx": "ppt/media/", ".xlsx": "xl/media/"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def shown_box(box, crop, rotation):
    """A box [x0, y0, x1, y1] in PDF user space, on the page as it is shown: the crop box's corner at the origin,
    the page turned clockwise by rotation (0, 90, 180, 270), y up. This is the frame pdfium renders."""
    l, b, r, t = crop
    x0, y0, x1, y1 = box
    rot = rotation % 360
    if rot == 90:
        xs, ys = (y0 - b, y1 - b), (r - x1, r - x0)
    elif rot == 180:
        xs, ys = (r - x1, r - x0), (t - y1, t - y0)
    elif rot == 270:
        xs, ys = (t - y1, t - y0), (x0 - l, x1 - l)
    else:
        xs, ys = (x0 - l, x1 - l), (y0 - b, y1 - b)
    return [xs[0], ys[0], xs[1], ys[1]]


def _pdf(src, out):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    images = []
    doc = pdfium.PdfDocument(str(src))
    tool = {"pypdfium2": str(pdfium.PYPDFIUM_INFO), "pdfium": str(pdfium.PDFIUM_INFO)}
    for pi in range(len(doc)):
        page = doc[pi]
        w, h = page.get_size()
        crop, rotation = page.get_cropbox(), page.get_rotation()
        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=8):
            pw, ph = obj.get_px_size()
            n = len(images) + 1
            name = f"p{pi + 1:03d}-i{n:03d}.png"
            obj.get_bitmap(render=False).to_pil().save(out / name)
            rec = {"id": n, "file": name, "px": [int(pw), int(ph)], "page": pi + 1,
                   "page_size_pt": [round(w, 3), round(h, 3)]}
            if obj.level > 0:
                rec["in_form"] = True
            else:
                x0, y0, x1, y1 = shown_box(obj.get_bounds(), crop, rotation)
                rec["bbox_pt"] = [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]
            images.append(rec)
    return images, tool


def _office(src, out, prefix):
    from PIL import Image
    images = []
    with zipfile.ZipFile(src) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            if not info.filename.startswith(prefix) or Path(info.filename).suffix.lower() not in IMAGE_EXT:
                continue
            data = z.read(info)
            n = len(images) + 1
            name = f"m{n:03d}-{Path(info.filename).name}"
            (out / name).write_bytes(data)
            try:
                px = list(Image.open(io.BytesIO(data)).size)
            except Exception:  # an image the reader cannot open is kept and marked, not dropped
                px = None
            images.append({"id": n, "file": name, "px": px, "part": info.filename})
    return images, {}


def extract(src, out):
    src, out = Path(src), Path(out)
    ext = src.suffix.lower()
    if ext != ".pdf" and ext not in OFFICE:
        raise ValueError(f"not a PDF or Office document: {src}")
    out.mkdir(parents=True, exist_ok=True)
    if ext == ".pdf":
        images, tool = _pdf(src, out)
    else:
        images, tool = _office(src, out, OFFICE[ext])
    man = {"source": {"path": str(src), "sha256": _sha256(src), "bytes": src.stat().st_size},
           "tool": {**tool, "script": "document-maps/extract_images.py"}, "images": images}
    (out / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    return man


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("document")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    man = extract(a.document, a.out)
    print(json.dumps({"images": len(man["images"]), "out": a.out}))
    sys.exit(0)


if __name__ == "__main__":
    main()
