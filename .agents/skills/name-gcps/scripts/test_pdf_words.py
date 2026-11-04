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
