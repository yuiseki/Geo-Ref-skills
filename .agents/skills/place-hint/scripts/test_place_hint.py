# uvx --with pytest pytest scripts/test_place_hint.py
import math

import pytest

import place_hint


def cand(name, lon, lat, importance=0.5):
    return {"name": name, "lon": lon, "lat": lat, "importance": importance, "display_name": name}


def test_picks_the_place_where_several_names_agree():
    cands = {
        # three names that all have a candidate in Kanazawa, plus decoys elsewhere
        "Korinbo": [cand("Korinbo", 136.656, 36.561)],
        "Katamachi": [cand("Katamachi", 136.652, 36.556), cand("Katamachi", 139.0, 35.0)],
        "Kenrokuen": [cand("Kenrokuen", 136.662, 36.562)],
        "Asahi": [cand("Asahi", 140.5, 35.7), cand("Asahi", 142.3, 43.8), cand("Asahi", 130.4, 33.6)],
    }
    h = place_hint.cluster(cands, radius_km=10, min_support=3)
    assert h["status"] == "ok"
    assert sorted(h["support"]) == ["Katamachi", "Kenrokuen", "Korinbo"]
    w, s, e, n = h["bbox"]
    assert w < 136.652 < e and s < 36.556 < n
    assert e - w < 0.5


def test_too_few_agreeing_names_is_a_declared_failure():
    cands = {
        "A": [cand("A", 136.0, 36.0)],
        "B": [cand("B", 140.0, 38.0)],
        "C": [cand("C", 130.0, 33.0)],
    }
    h = place_hint.cluster(cands, radius_km=10, min_support=3)
    assert h["status"] == "failed"
    assert "support" in h["reason"]


def test_one_name_with_many_candidates_counts_once():
    cands = {"Asahi": [cand("Asahi", 136.0 + i * 0.01, 36.0) for i in range(10)], "B": [cand("B", 136.02, 36.0)]}
    h = place_hint.cluster(cands, radius_km=10, min_support=3)
    assert h["status"] == "failed"


def test_haversine():
    assert place_hint.haversine_km(0, 0, 0, 1) == pytest.approx(111.19, rel=1e-3)
    assert place_hint.haversine_km(139.0, 35.0, 139.0, 35.0) == 0


@pytest.mark.parametrize("raw,want", [
    ("KUDAN-KITA", "KUDAN-KITA"), ("(42)", None), ("2-CHOME", None), ("の", None), ("吹上", "吹上"),
    ("/ATION", None), ("Station", None), ("iZOMON", None), ("KANDA,", "KANDA"), ("Mi", None), ("HOME", None),
])
def test_name_filter(raw, want):
    assert place_hint.clean_name(raw) == want


def test_margin_is_applied_and_bbox_order():
    cands = {k: [cand(k, 136.65 + d, 36.56 + d)] for k, d in [("A", 0.0), ("B", 0.01), ("C", 0.02)]}
    h = place_hint.cluster(cands, radius_km=10, min_support=3, margin_km=2, min_weight=0)
    w, s, e, n = h["bbox"]
    assert w < 136.65 and e > 136.67 and s < 36.56 and n > 36.58
    assert (136.67 - 136.65) < (e - w)
    assert math.isclose((e - w) - 0.02, 2 * 2 / (111.32 * math.cos(math.radians(36.57))), rel_tol=0.05)


def test_exact_hits_drop_loose_matches():
    hits = [
        {"name": "昭和通り", "namedetails": {"name": "昭和通り", "name:en": "Showa-dori avenue"}},
        {"name": "神田神保町", "namedetails": {"name": "神田神保町", "name:ja-Latn": "Kanda-Jimbōchō"}},
    ]
    assert place_hint.exact_hits("DORI", hits) == []
    assert place_hint.exact_hits("KANDA-JIMBOCHO", hits) == [hits[1]]
    assert place_hint.exact_hits("神田神保町", hits) == [hits[1]]


def test_norm():
    assert place_hint.norm("Kanda-Jimbōchō") == place_hint.norm("KANDA JIMBOCHO")
    assert place_hint.norm("Showa-dori avenue") != place_hint.norm("DORI")


def test_common_names_weigh_little():
    common = lambda n: [cand(n, 130.0 + i, 33.0 + 0.5 * i) for i in range(10)]
    cands = {"CHUO": common("CHUO"), "KITA": common("KITA"), "HIGASHI": common("HIGASHI"),
             "Korinbo": [cand("Korinbo", 136.656, 36.561)], "Kenrokuen": [cand("Kenrokuen", 136.662, 36.562)],
             "Katamachi": [cand("Katamachi", 136.652, 36.556)]}
    h = place_hint.cluster(cands)
    assert h["status"] == "ok" and sorted(h["support"]) == ["Katamachi", "Kenrokuen", "Korinbo"]
    only_common = {k: v for k, v in cands.items() if k in ("CHUO", "KITA", "HIGASHI")}
    assert place_hint.cluster(only_common)["status"] == "failed"
