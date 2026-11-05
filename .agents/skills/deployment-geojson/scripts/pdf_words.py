"""Words and point symbols from a PDF page's text layer, for maps drawn as vector PDFs.

    python scripts/pdf_words.py map.pdf --page 1 --dpi 150 [--box-px x0 y0 x1 y1] --out words.json

Maps exported from GIS or drawing software (the UN peacekeeping maps: Adobe Illustrator, 2026-11-04) keep their
labels as text: every character's box, font and size, with diacritics right (Dračevo, Štimlje), where tesseract
reads a rendering of them only in part. Point symbols drawn with a symbol font (ESRIDefaultMarker) are
characters too, at their exact place.

- `chars(path, page)`: every character, in page points with the origin at the top left.
- `words(chars)`: characters on one line, of one size and font, with no space and a gap under 0.3 of the size
  between them, as words ("kind": "word"). Labels are often cut into runs by kerning ("T" + "ropojë"); a run
  ending in a capital joins the next across a gap under 0.6 of the size. Neighbouring words on one line, under
  0.6 of the size apart, also make phrases ("kind": "phrase", "Kosovo Polje"), as ocr_words.py does.
- `markers(chars)`: characters of symbol fonts (names with Marker, Symbol or Dingbat), as points.
- `to_pixels(word, dpi, origin_px)`: a word in the pixels of a rendering at dpi, cropped at origin_px, in the
  form name_gcps.py takes (text, conf 100, col, row, w, h).
"""

import argparse
import ctypes
import json
import re
from pathlib import Path

SYMBOL_FONT = re.compile(r"marker|symbol|dingbat|wingding", re.IGNORECASE)


def page_frame(page):
    """(rotation, W0, H0, x0, y0) of a page: W0 x H0 its shown box unturned, (x0, y0) that box's bottom left in the
    page's space. The page is shown cut to its CropBox, which need not start at the origin: WFP's access constraints
    maps (2025-2026) are landscape sheets printed on a portrait page and cut out by a CropBox (0, 229, 612, 562)."""
    rot = page.get_rotation()
    W0, H0 = page.get_size()
    if rot % 180:
        W0, H0 = H0, W0
    x0, y0, _, _ = page.get_cropbox()
    return rot, W0, H0, x0, y0


def display(x, y, rotation, W0, H0, x0=0.0, y0=0.0):
    """A point of the unturned page (origin bottom left, as the text layer and paths give it) where the page is
    shown: origin top left, after /Rotate (clockwise, in quarter turns), W0 x H0 being the unturned size of the
    shown box and (x0, y0) its bottom left (page_frame)."""
    x, y = x - x0, y - y0
    r = rotation % 360
    if r == 90:
        return y, x
    if r == 180:
        return W0 - x, y
    if r == 270:
        return H0 - y, W0 - x
    return x, H0 - y


def display_box(l, b, r, t, rotation, W0, H0, x0=0.0, y0=0.0):
    """A box of the unturned page (left, bottom, right, top) as shown: (left, top, right, bottom), origin top left."""
    xs, ys = zip(display(l, b, rotation, W0, H0, x0, y0), display(r, t, rotation, W0, H0, x0, y0))
    return min(xs), min(ys), max(xs), max(ys)


def chars(path, page=1):
    import pypdfium2 as pdfium
    import pypdfium2.raw as R

    doc = pdfium.PdfDocument(str(path))
    p = doc[page - 1]
    # the text layer is in the unturned page's space; a page turned by /Rotate (UN maps of 2021 and 2022: portrait
    # pages turned a quarter) is shown, rendered and cropped turned, so every box is turned with it (2026-11-05)
    rot, W0, H0, x0, y0 = page_frame(p)
    tp = p.get_textpage()
    buf = ctypes.create_string_buffer(256)
    flags = ctypes.c_int()
    out = []
    for i in range(tp.count_chars()):
        u = R.FPDFText_GetUnicode(tp.raw, i)
        R.FPDFText_GetFontInfo(tp.raw, i, buf, 256, ctypes.byref(flags))
        l, r, b, t = (ctypes.c_double() for _ in range(4))
        R.FPDFText_GetCharBox(tp.raw, i, ctypes.byref(l), ctypes.byref(r), ctypes.byref(b), ctypes.byref(t))
        # the font size the text layer reports is often 1, the size being in the text matrix (Illustrator exports,
        # 2026-11-04); the loose box (ascent to descent) has the same height for every letter of a font and size
        loose = R.FS_RECTF()
        R.FPDFText_GetLooseCharBox(tp.raw, i, ctypes.byref(loose))
        L, T, Rr, B = display_box(l.value, b.value, r.value, t.value, rot, W0, H0, x0, y0)
        _, lt, _, lb = display_box(loose.left, loose.bottom, loose.right, loose.top, rot, W0, H0, x0, y0)
        size = abs(lb - lt) / 1.15
        cr, cg, cb, ca = (ctypes.c_uint() for _ in range(4))
        colour = ((cr.value, cg.value, cb.value) if R.FPDFText_GetFillColor(
            tp.raw, i, ctypes.byref(cr), ctypes.byref(cg), ctypes.byref(cb), ctypes.byref(ca)) else None)
        out.append({"ch": chr(u) if u else "", "font": buf.value.decode(errors="replace").split("+")[-1],
                    "size": size, "l": L, "r": Rr, "t": T, "b": B, "base": lb, "colour": colour})
    return out


def _box(cs):
    l, r = min(c["l"] for c in cs), max(c["r"] for c in cs)
    t, b = min(c["t"] for c in cs), max(c["b"] for c in cs)
    return {"x": (l + r) / 2, "y": (t + b) / 2, "w": r - l, "h": b - t, "l": l, "r": r}


def words(cs, gap=0.3, kern=0.6, phrase_gap=0.6):
    text_cs = [c for c in cs if c["ch"].strip() or c["ch"] == " "]
    text_cs = [c for c in text_cs if not SYMBOL_FONT.search(c["font"])]
    runs = []  # (chars) in reading order: the text layer lists a label's characters together
    for c in text_cs:
        if c["ch"] in (" ", "\n", "\r", "\t") or not c["ch"]:
            runs.append(None)
            continue
        last = runs[-1] if runs and runs[-1] else None
        if last:
            p = last[-1]
            same_line = (abs(c.get("base", c["b"]) - p.get("base", p["b"])) < 0.3 * c["size"]
                         and abs(c["size"] - p["size"]) < 0.1 * c["size"])
            g = c["l"] - p["r"]
            limit = (kern if p["ch"].isupper() and len(last) == 1 else gap) * c["size"]
            if same_line and c["font"] == p["font"] and c.get("colour") == p.get("colour") and -0.2 * c["size"] < g < limit:
                last.append(c)
                continue
        runs.append([c])
    ws = []
    for r in runs:
        if r:
            t = "".join(c["ch"] for c in r)
            ws.append({"text": t, "kind": "word", "size": r[0]["size"], "font": r[0]["font"], **_box(r),
                       "colour": r[0].get("colour"), "_b": r[-1].get("base", r[-1]["b"])})
    out = list(ws)
    # phrases: up to four neighbouring words of one line, size and font
    for i in range(len(ws)):
        group = [ws[i]]
        for j in range(i + 1, min(i + 4, len(ws))):
            a, b = group[-1], ws[j]
            if (b["font"] != a["font"] or abs(b["size"] - a["size"]) > 0.1 * a["size"]
                    or abs(b["_b"] - a["_b"]) > 0.3 * a["size"] or not 0 <= b["l"] - a["r"] < phrase_gap * a["size"]):
                break
            group.append(b)
            out.append({"text": " ".join(g["text"] for g in group), "kind": "phrase", "size": a["size"], "font": a["font"],
                        "colour": a.get("colour"),
                        **_box([{"l": g["l"], "r": g["r"], "t": g["y"] - g["h"] / 2, "b": g["y"] + g["h"] / 2} for g in group]),
                        "_b": b["_b"]})
    for w in out:
        w.pop("_b", None)
        w.pop("l", None)
        w.pop("r", None)
    return out


def markers(cs):
    return [{"x": (c["l"] + c["r"]) / 2, "y": (c["t"] + c["b"]) / 2, "font": c["font"], "ch": c["ch"], "size": c["size"]}
            for c in cs if SYMBOL_FONT.search(c["font"])]


def to_pixels(w, dpi, origin_px=(0, 0)):
    k = dpi / 72.0
    return {"text": w["text"], "kind": w.get("kind", "word"), "conf": 100.0, "col": w["x"] * k - origin_px[0],
            "row": w["y"] * k - origin_px[1], "w": w["w"] * k, "h": w["h"] * k, "font": w.get("font"),
            "size": w.get("size")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=float, default=150)
    ap.add_argument("--box-px", type=float, nargs=4, default=None, help="the crop of the rendering, in its pixels")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cs = chars(a.pdf, a.page)
    o = (a.box_px[0], a.box_px[1]) if a.box_px else (0, 0)
    res = {"words": [to_pixels(w, a.dpi, o) for w in words(cs)],
           "markers": [{**to_pixels({"text": m["ch"], "x": m["x"], "y": m["y"], "w": 0, "h": 0}, a.dpi, o), "font": m["font"]}
                       for m in markers(cs)]}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"words": len(res["words"]), "markers": len(res["markers"])}))


if __name__ == "__main__":
    main()
