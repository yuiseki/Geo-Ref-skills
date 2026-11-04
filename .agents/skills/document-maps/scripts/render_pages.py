"""Draw PDF pages as images, for maps drawn as vectors (common in government PDFs) that are no image object.

    python scripts/render_pages.py report.pdf --out tmp/doc/pages --dpi 200 [--pages 1 3]

Writes p001.png ... and manifest.json: the document's sha256, pypdfium2 and pdfium versions, and per page its
number (1-based), dpi, size in points and in pixels. Pixel (col, row) of PDF point (x, y) is
(x * dpi / 72, (height_pt - y) * dpi / 72), corner convention (pt_to_px). Record the dpi with every result: a
pixel is only a size on the ground once the dpi and the printed scale are known.

A large page at a high dpi is a large image (A1 at 400 dpi is about 13,000 x 9,000 px); keep the dpi as low as
the map's lines allow and cap the process's memory when going higher.
"""

import argparse
import json
import sys
from pathlib import Path

from extract_images import _sha256


def pt_to_px(x, y, page):
    s = page["dpi"] / 72.0
    return x * s, (page["page_size_pt"][1] - y) * s


def render(src, out, dpi=150, pages=None):
    import pypdfium2 as pdfium
    src, out = Path(src), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(src))
    recs = []
    for pi in range(len(doc)):
        if pages and pi + 1 not in pages:
            continue
        page = doc[pi]
        w, h = page.get_size()
        im = page.render(scale=dpi / 72.0).to_pil()
        name = f"p{pi + 1:03d}.png"
        im.save(out / name)
        recs.append({"page": pi + 1, "file": name, "dpi": dpi, "page_size_pt": [round(w, 3), round(h, 3)],
                     "px": list(im.size)})
    man = {"source": {"path": str(src), "sha256": _sha256(src), "bytes": src.stat().st_size},
           "tool": {"pypdfium2": str(pdfium.PYPDFIUM_INFO), "pdfium": str(pdfium.PDFIUM_INFO),
                    "script": "document-maps/render_pages.py"}, "pages": recs}
    (out / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    return man


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("document")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi", type=float, default=150)
    ap.add_argument("--pages", type=int, nargs="*")
    a = ap.parse_args()
    man = render(a.document, a.out, a.dpi, a.pages)
    print(json.dumps({"pages": len(man["pages"]), "out": a.out}))
    sys.exit(0)


if __name__ == "__main__":
    main()
