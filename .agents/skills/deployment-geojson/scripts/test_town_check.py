# uvx --with pytest --with numpy pytest scripts/test_town_check.py
import math

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


def word(text, x, y, w=30):
    return {"text": text, "x": x, "y": y, "w": w, "kind": "word"}


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
    panel = {"model": Model(), "k": 1.0, "o": (0.0, 0.0)}
    X2, Y2 = wm.lonlat_to_mercator(30.01, 1.5)
    far = complex(*wm.lonlat_to_mercator(31.0, 1.5))
    d = T.distances([("Bunia", (1.0, 1.0))], panel, lambda name: [far, complex(X2, Y2)])
    assert d[0][1] == "Bunia" and d[0][0] == pytest.approx(1.11, abs=0.02)   # 0.01 degree at the equator


def test_a_name_with_no_place_is_not_measured():
    panel = {"model": None, "k": 1.0, "o": (0.0, 0.0)}
    assert T.distances([("Nowhere", (1.0, 1.0))], panel, lambda name: []) == []


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
