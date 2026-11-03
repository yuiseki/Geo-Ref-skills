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


def names_on_map(m_per_px, rot_deg, centre, n=8, seed=0, size=(900, 700)):
    """Place names at known image positions of a map drawn at m_per_px (mercator metres per pixel), turned by
    rot_deg, centred on centre (lon, lat)."""
    import random
    rnd = random.Random(seed)
    cx, cy = place_hint.lonlat_to_mercator(*centre)
    th = math.radians(rot_deg)
    pts = []
    for i in range(n):
        col, row = rnd.uniform(50, size[0] - 50), rnd.uniform(50, size[1] - 50)
        dx, dy = col - size[0] / 2, row - size[1] / 2
        # image (right, down) -> mercator (east, north): turn by -th, scale, flip the row axis
        ex = (dx * math.cos(th) + dy * math.sin(th)) * m_per_px
        ny = -(-dx * math.sin(th) + dy * math.cos(th)) * m_per_px
        lon, lat = place_hint.mercator_to_lonlat(cx + ex, cy + ny)
        pts.append({"name": f"N{i}", "col": col, "row": row, "lon": lon, "lat": lat})
    return pts


def test_scale_from_names_recovers_scale_rotation_and_zoom():
    pts = names_on_map(4.78, 12.0, (139.75, 35.68))  # 4.78 m/px is zoom 15
    s = place_hint.scale_from_names(pts, 900, 700)
    assert s["status"] == "ok", s
    assert s["m_per_px"] == pytest.approx(4.78, rel=1e-3)
    assert s["rotation_deg"] == pytest.approx(12.0, abs=0.1)
    assert s["zoom"] == 15 and s["inliers"] == 8
    w, so, e, n = s["bbox"]
    for p in pts:
        assert w < p["lon"] < e and so < p["lat"] < n


def test_scale_from_names_ignores_a_misplaced_name():
    pts = names_on_map(9.55, -20.0, (135.50, 34.69), n=7, seed=1)
    pts[3]["lon"] += 0.03  # a name looked up at the wrong place nearby
    s = place_hint.scale_from_names(pts, 900, 700)
    assert s["status"] == "ok" and s["inliers"] == 6 and "N3" not in s["support"]
    assert s["m_per_px"] == pytest.approx(9.55, rel=1e-2) and s["zoom"] == 14


def test_scale_from_names_needs_four_agreeing_names():
    # two or three names always fit a similarity; they cannot show that the fit is right
    assert place_hint.scale_from_names(names_on_map(4.78, 0, (139.75, 35.68), n=3), 900, 700)["status"] == "failed"


def test_scale_from_names_refuses_names_that_do_not_agree():
    import random
    rnd = random.Random(3)
    pts = [{"name": f"N{i}", "col": rnd.uniform(0, 900), "row": rnd.uniform(0, 700),
            "lon": 139.7 + rnd.uniform(-0.05, 0.05), "lat": 35.68 + rnd.uniform(-0.05, 0.05)} for i in range(8)]
    assert place_hint.scale_from_names(pts, 900, 700)["status"] == "failed"


def test_mercator_round_trip():
    x, y = place_hint.lonlat_to_mercator(139.75, 35.68)
    lon, lat = place_hint.mercator_to_lonlat(x, y)
    assert lon == pytest.approx(139.75) and lat == pytest.approx(35.68)


def test_located_points_take_the_most_confident_reading_of_each_name():
    words = [{"text": "KORINBO", "conf": 80, "col": 10, "row": 20}, {"text": "KORINBO", "conf": 95, "col": 11, "row": 21},
             {"text": "片町", "conf": 90, "col": 30, "row": 40}, {"text": "OTHER", "conf": 99, "col": 0, "row": 0}]
    matches = {"KORINBO": {"lon": 136.656, "lat": 36.561}, "片町": {"lon": 136.652, "lat": 36.556}}
    pts = place_hint.located_points(words, matches)
    assert [(p["name"], p["col"]) for p in pts] == [("KORINBO", 11), ("片町", 30)]


def test_zoom_is_the_one_no_coarser_than_the_map():
    # 6.26 m/px lies between z15 (4.78) and z14 (9.55); the reference must not be coarser than the map
    assert place_hint.scale_from_names(names_on_map(6.26, 0, (139.75, 35.68)), 900, 700)["zoom"] == 15
