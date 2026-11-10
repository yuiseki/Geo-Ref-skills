# uvx --with pytest --with numpy pytest scripts/test_town_check.py

import pytest

import town_check as T
import webmercator as wm


def circle(x, y, r=2.0):
    return {"box": [x - r, y - r, x + r, y + r], "segs": [(1, None, None)] * 4}


def test_town_symbols_are_the_small_round_paths():
    paths = [circle(100, 100),
             circle(200, 200, r=10),                                   # too big: a unit frame or a lake
             {"box": [0, 0, 6, 2], "segs": [(1, None, None)]},         # not round
             {"box": [50, 50, 54, 54], "segs": [(0, None, None)]}]    # straight lines only: a square
    assert T.town_symbols(paths) == [(100.0, 100.0)]


def word(text, x, y, w=30, h=8):
    return {"text": text, "x": x, "y": y, "w": w, "h": h, "kind": "word"}


def test_a_name_is_paired_with_the_town_symbol_beside_it():
    syms = [(100.0, 100.0), (400.0, 400.0)]
    ws = [word("Bunia", 120, 100), word("BANGLADESH", 100, 105), word("Km", 400, 405), word("Route 4", 400, 395),
          word("Far", 250, 250)]
    assert T.pairs(ws, syms) == [("Bunia", (100.0, 100.0))]


def test_distances_are_kilometres_on_the_ground_to_the_nearest_place_of_that_name():
    X, Y = wm.lonlat_to_mercator(30.0, 1.5)

    class Model:
        def predict(self, pts):
            return [[X, Y] for _ in pts]
    panel = whole_panel(Model())
    X2, Y2 = wm.lonlat_to_mercator(30.01, 1.5)
    far = complex(*wm.lonlat_to_mercator(31.0, 1.5))
    d = T.distances([("Bunia", (50.0, 50.0))], [panel], lambda name: [far, complex(X2, Y2)])
    assert d[0][1] == "Bunia" and d[0][0] == pytest.approx(1.11, abs=0.02)   # 0.01 degree at the equator


def test_a_name_with_no_place_is_not_measured():
    assert T.distances([("Nowhere", (50.0, 50.0))], [whole_panel(None)], lambda name: []) == []


def whole_panel(model, box=(0, 0, 100, 100), cand=1):
    import numpy as np
    x0, y0, x1, y1 = box
    src = np.array([[0, 0], [x1 - x0, 0], [x1 - x0, y1 - y0], [0, y1 - y0]], float)
    return {"model": model, "k": 1.0, "o": (x0, y0), "W": x1 - x0, "H": y1 - y0, "src": src, "local": False,
            "cand": cand, "area": (x1 - x0) * (y1 - y0)}


def test_a_town_in_an_inset_is_placed_by_the_inset_not_by_the_main_map():
    # MONUSCO 2025: the towns of the eastern inset went through the main map's model and came out 1,000 km off
    # (Komanda, Eringeti), so the map's median was 136 km; the units are placed by the inset (2026-11-10)
    main_at, inset_at = wm.lonlat_to_mercator(20.0, 0.0), wm.lonlat_to_mercator(29.8, 1.4)

    class At:
        def __init__(self, xy):
            self.xy = xy

        def predict(self, pts):
            return [list(self.xy) for _ in pts]
    inset = whole_panel(At(inset_at), box=(60, 60, 100, 100), cand=2)
    main = whole_panel(At(main_at), box=(0, 0, 100, 100), cand=1)
    d = T.distances([("Komanda", (80.0, 80.0))], [inset, main], lambda name: [complex(*inset_at)])
    assert d[0][0] == pytest.approx(0.0, abs=0.01)


def test_a_town_outside_every_panel_is_not_measured():
    X, Y = wm.lonlat_to_mercator(30.0, 1.5)

    class Model:
        def predict(self, pts):
            return [[X, Y] for _ in pts]
    assert T.distances([("Kampala", (500.0, 500.0))], [whole_panel(Model())], lambda name: [complex(X, Y)]) == []


def test_the_summary_reads_the_middle_not_the_worst():
    s = T.summarise([(1.0, "a"), (2.0, "b"), (3.0, "c"), (2500.0, "Camp")])   # a same-name place far away
    assert s["n"] == 4 and s["median"] == 2.5 and s["over10"] == 1 and s["worst"] == [["Camp", 2500.0]]
    assert T.summarise([]) == {"n": 0, "median": None, "p25": None, "p75": None, "over10": 0, "worst": []}


def test_a_map_passes_when_enough_towns_sit_within_the_limit():
    assert T.passes({"n": 5, "median": 9.8}, limit_km=10)
    assert T.passes({"n": 5, "median": 10.0}, limit_km=10)
    assert not T.passes({"n": 5, "median": 13.4}, limit_km=10)
    assert not T.passes({"n": 2, "median": 1.0}, limit_km=10)      # too few towns to say: not checked, not passed
    assert not T.passes({"n": 0, "median": None}, limit_km=10)


def test_the_town_check_is_recorded_in_the_file():
    fc = {"type": "FeatureCollection", "checks": {"hull_margin": 0.3}, "features": []}
    s = {"n": 5, "median": 2.0, "p25": 1.0, "p75": 3.0, "over10": 0, "worst": [["x", 3.0]]}
    out = T.with_town(fc, s, limit_km=10)
    assert out["checks"] == {"hull_margin": 0.3, "town": {"n": 5, "median_km": 2.0, "limit_km": 10, "passed": True}}
    assert fc["checks"] == {"hull_margin": 0.3}   # the given collection is not changed


def test_a_round_shape_inside_the_name_is_not_its_town_symbol():
    # MINUSCA 2025: a round path inside the label (part of the lettering) was taken for the town, and the map's
    # median came out 30 km though its control points, the same towns' symbols, agreed within 2 px (2026-11-10)
    w = {**word("Bangui", 300, 444, w=33), "h": 8}
    syms = [(301.0, 444.5), (280.0, 452.0)]
    assert T.pairs([w], syms) == [("Bangui", (280.0, 452.0))]


def test_a_name_with_only_a_round_shape_inside_it_has_no_town():
    w = {**word("Bangui", 300, 444, w=33), "h": 8}
    assert T.pairs([w], [(301.0, 444.5)]) == []


def test_a_word_inside_a_longer_label_is_not_a_name_of_its_own():
    # UNDOF 2025: "Kafr" of "Kafr Shams" was looked up alone and matched a Kafr 120 km away, three times (2026-11-10)
    kafr = {"text": "Kafr", "kind": "word", "x": 100, "y": 50, "w": 20, "h": 6}
    shams = {"text": "Shams", "kind": "word", "x": 126, "y": 50, "w": 24, "h": 6}
    both = {"text": "Kafr Shams", "kind": "phrase", "x": 114, "y": 50, "w": 48, "h": 6}
    alone = {"text": "Nawa", "kind": "word", "x": 300, "y": 80, "w": 20, "h": 6}
    assert [w["text"] for w in T.labels([kafr, shams, both, alone])] == ["Kafr Shams", "Nawa"]


def test_the_longest_phrase_is_the_label_not_its_shorter_phrases():
    a = {"text": "Jubata", "kind": "word", "x": 10, "y": 5, "w": 20, "h": 6}
    ab = {"text": "Jubata al", "kind": "phrase", "x": 15, "y": 5, "w": 30, "h": 6}
    abc = {"text": "Jubata al Khashab", "kind": "phrase", "x": 30, "y": 5, "w": 60, "h": 6}
    assert [w["text"] for w in T.labels([a, ab, abc])] == ["Jubata al Khashab"]


def test_a_symbol_two_names_reach_is_the_town_of_the_nearer_name_only():
    # MONUSCO 2025: Lubumbashi (drawn with another symbol) took the ring of Kolwezi beside it and came out 254 km off
    syms = [(100.0, 100.0)]
    kolwezi = {**word("Kolwezi", 112, 100, w=20), "h": 6}
    lubumbashi = {**word("Lubumbashi", 120, 108, w=36), "h": 6}
    assert T.pairs([lubumbashi, kolwezi], syms) == [("Kolwezi", (100.0, 100.0))]


def test_a_long_name_reaches_no_farther_than_a_short_one():
    # the reach is from the label's box, 1.2 times its height (name-gcps's symbol_options), not from its centre:
    # from the centre, a long name reached the ring of the town beside it (Lubumbashi and Kolwezi, MONUSCO 2025)
    lub = word("Lubumbashi", 331.5, 467.9, w=45.4, h=6.5)
    kol = word("Kolwezi", 336.7, 446.9, w=28.2, h=6.5)
    assert T.pairs([lub, kol], [(319.1, 454.1)]) == [("Kolwezi", (319.1, 454.1))]
    assert T.pairs([lub], [(319.1, 454.1)]) == []


def test_the_main_panel_s_ground_diagonal_is_recorded_beside_the_median():
    # a median in km means more on a city map than on a map of the DRC: the record carries the scale too
    X0, Y0 = wm.lonlat_to_mercator(20.0, 0.0)
    X1, Y1 = wm.lonlat_to_mercator(21.0, 0.0)

    class Lin:
        def predict(self, pts):
            return [[X0 + (X1 - X0) * c / 100.0, Y0] for c, r in pts]
    p = whole_panel(Lin())
    assert T.extent_km([p]) == pytest.approx(111.3, abs=0.5)  # (0,0) to (100,100): 1 degree east at the equator
