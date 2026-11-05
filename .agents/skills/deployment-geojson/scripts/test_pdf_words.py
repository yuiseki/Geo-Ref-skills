# uvx --with pypdfium2 --with pytest pytest scripts/test_pdf_words.py
import pdf_words as pw


def ch(c, x, y=100.0, size=10.0, font="ArialMT", w=None):
    """A character box in page points, top-left origin: left x, baseline-ish top y."""
    w = w if w is not None else 0.55 * size
    return {"ch": c, "font": font, "size": size, "l": x, "r": x + w, "t": y - size, "b": y}


def word_of(text, x, y=100.0, size=10.0, font="ArialMT", gap=0.0):
    out, cx = [], x
    for c in text:
        out.append(ch(c, cx, y, size, font))
        cx += 0.55 * size + gap
    return out


def test_letters_on_one_line_make_a_word_and_a_kerned_capital_joins_it():
    # "T" + "ropojë" come as two text runs with a kerning gap; they are one word
    cs = word_of("T", 50) + word_of("ropojë", 50 + 0.55 * 10 + 0.8)
    ws = pw.words(cs)
    assert [w["text"] for w in ws if w["kind"] == "word"] == ["Tropojë"]


def test_a_space_or_a_wide_gap_splits_words_and_a_phrase_joins_them():
    cs = word_of("Kosovo", 10) + [ch(" ", 43)] + word_of("Polje", 48.5)
    ws = pw.words(cs)
    assert sorted(w["text"] for w in ws if w["kind"] == "word") == ["Kosovo", "Polje"]
    assert [w["text"] for w in ws if w["kind"] == "phrase"] == ["Kosovo Polje"]


def test_words_on_different_lines_or_sizes_stay_apart():
    cs = word_of("Banja", 10, y=100) + word_of("Brus", 10, y=113)
    assert sorted(w["text"] for w in pw.words(cs) if w["kind"] == "word") == ["Banja", "Brus"]
    assert not [w for w in pw.words(cs) if w["kind"] == "phrase"]


def test_marker_glyphs_are_symbols_not_words():
    cs = word_of("Lece", 10) + [ch("o", 3, font="ESRIDefaultMarker", size=6, w=4)]
    assert [w["text"] for w in pw.words(cs)] == ["Lece"]
    m = pw.markers(cs)
    assert len(m) == 1 and abs(m[0]["x"] - 5) < 1e-9 and abs(m[0]["y"] - 97) < 1e-9


def test_to_pixels_puts_page_points_in_a_cropped_rendering():
    w = {"text": "Lece", "kind": "word", "x": 72.0, "y": 144.0, "w": 36.0, "h": 9.0, "size": 9.0}
    p = pw.to_pixels(w, dpi=144, origin_px=(10, 20))
    assert (p["col"], p["row"], p["w"], p["h"]) == (134.0, 268.0, 72.0, 18.0)
    assert p["conf"] == 100.0


def text_pdf(path, rotation, x=100.0, y=600.0, text="Bunia", crop=None):
    import ctypes
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(612, 792)
    obj = raw.FPDFPageObj_NewTextObj(doc.raw, b"Helvetica", ctypes.c_float(12.0))
    ws = (text + "\0").encode("utf-16-le")
    raw.FPDFText_SetText(obj, ctypes.cast(ctypes.c_char_p(ws), ctypes.POINTER(raw.FPDF_WCHAR)))
    raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
    raw.FPDFPage_InsertObject(pg.raw, obj)
    pg.gen_content()
    if crop:
        pg.set_cropbox(*crop)
    pg.set_rotation(rotation)
    doc.save(str(path))


def test_a_rotated_page_gives_characters_where_they_are_drawn(tmp_path):
    # many UN maps of 2021 to 2022 are portrait pages turned by /Rotate 90; the text layer is in the unturned
    # page's space, and the words came out on the wrong side of the map (2026-11-05)
    text_pdf(tmp_path / "r0.pdf", 0)
    text_pdf(tmp_path / "r90.pdf", 90)
    a = pw.chars(tmp_path / "r0.pdf")[0]
    b = pw.chars(tmp_path / "r90.pdf")[0]
    # turned a quarter clockwise: top-left page point (x, y) is shown at (792 - y, x)
    assert abs(b["l"] - (792 - a["b"])) < 0.5 and abs(b["t"] - a["l"]) < 0.5
    import pypdfium2 as pdfium
    W, H = pdfium.PdfDocument(str(tmp_path / "r90.pdf"))[0].get_size()
    assert 0 <= b["l"] <= W and 0 <= b["t"] <= H


def test_a_cropped_page_gives_characters_where_they_are_shown(tmp_path):
    # WFP's access constraints maps (2025-2026) are landscape sheets printed on a portrait page and cut out by a
    # CropBox that does not start at the page's origin; every word came out above the page (y < 0, 2026-11-05)
    crop = (30.0, 229.0, 612.0, 561.6)
    text_pdf(tmp_path / "full.pdf", 0, y=400.0)
    text_pdf(tmp_path / "crop.pdf", 0, y=400.0, crop=crop)
    a = pw.chars(tmp_path / "full.pdf")[0]
    b = pw.chars(tmp_path / "crop.pdf")[0]
    assert abs(b["l"] - (a["l"] - crop[0])) < 0.5
    assert abs(b["t"] - (a["t"] - (792 - crop[3]))) < 0.5
    import pypdfium2 as pdfium
    W, H = pdfium.PdfDocument(str(tmp_path / "crop.pdf"))[0].get_size()
    assert 0 <= b["l"] <= W and 0 <= b["t"] <= H


def test_a_cropped_and_rotated_page_gives_characters_where_they_are_shown(tmp_path):
    crop = (30.0, 229.0, 612.0, 561.6)
    text_pdf(tmp_path / "crop.pdf", 0, y=400.0, crop=crop)
    text_pdf(tmp_path / "crop90.pdf", 90, y=400.0, crop=crop)
    a = pw.chars(tmp_path / "crop.pdf")[0]
    b = pw.chars(tmp_path / "crop90.pdf")[0]
    h = crop[3] - crop[1]
    # turned a quarter clockwise: a shown point (x, y) of the unturned crop goes to (h - y, x)
    assert abs(b["l"] - (h - a["b"])) < 0.5 and abs(b["t"] - a["l"]) < 0.5
