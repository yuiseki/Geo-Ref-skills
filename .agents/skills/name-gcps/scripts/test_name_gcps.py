# uvx --with numpy --with opencv-python-headless --with pytest pytest scripts/test_name_gcps.py
import cmath
import math
import random

import cv2
import numpy as np

import name_gcps as ng


def ring_image(rings, size=(200, 160), r=4.0):
    img = np.full((size[1], size[0]), 255, np.uint8)
    for c, rr in rings:
        cv2.circle(img, (int(c), int(rr)), int(r), 0, 1, lineType=cv2.LINE_AA)
    return img


def test_a_ring_scores_high_and_a_filled_square_low():
    img = ring_image([(50, 40)])
    cv2.rectangle(img, (120, 100), (130, 110), 0, -1)
    s = ng.ring_score(img)
    assert s[40, 50] > 0.6
    assert s[105, 125] < 0.4


def test_a_filled_dot_scores_high_and_a_larger_filled_square_low():
    img = np.full((160, 200), 255, np.uint8)
    cv2.circle(img, (50, 40), 3, 100, -1, lineType=cv2.LINE_AA)
    cv2.rectangle(img, (120, 100), (134, 114), 0, -1)
    s = ng.ring_score(img)
    assert s[40, 50] > 0.6
    assert s[107, 127] < 0.4


def test_peaks_inside_a_word_are_dropped():
    img = ring_image([(50, 40), (150, 120)])
    words = [{"text": "Obilic", "conf": 90, "col": 150, "row": 120, "w": 40, "h": 14}]
    peaks = ng.symbol_peaks(ng.ring_score(img), words, min_score=0.5)
    assert len(peaks) == 1
    assert abs(peaks[0]["col"] - 50) <= 1 and abs(peaks[0]["row"] - 40) <= 1


def test_letter_boxes_leave_out_a_symbol_read_as_a_letter():
    words = [{"text": "Srbicao", "conf": 86, "col": 70, "row": 10, "w": 70, "h": 14},   # ring read as o
             {"text": "Srbica", "conf": 90, "col": 65, "row": 10, "w": 60, "h": 14},
             {"text": "\u00b0Novi", "conf": 64, "col": 25, "row": 40, "w": 50, "h": 14},  # ring read as a degree sign
             {"text": "Kosovo", "conf": 90, "col": 60, "row": 80, "w": 60, "h": 20},
             {"text": "yp", "conf": 49, "col": 60, "row": 120, "w": 50, "h": 50}]          # noise
    boxes = ng.letter_boxes(words)
    inside = lambda x, y: any(abs(x - b[0]) <= b[2] / 2 and abs(y - b[1]) <= b[3] / 2 for b in boxes)
    assert not inside(102, 10)      # the last tenth of Srbicao
    assert inside(60, 10)
    assert not inside(3, 40)        # the first fifth of the degree-sign reading
    assert inside(35, 40)
    assert inside(85, 80)           # the final o of Kosovo is a letter
    assert not inside(60, 120)


def test_labels_take_three_letter_town_names_in_title_case():
    words = [{"text": t, "conf": 90, "col": 1, "row": 1, "w": 5, "h": 5} for t in ("Wau", "Bor", "WAU", "the", "Wa")]
    assert sorted(ng.labels(words)) == ["Bor", "Wau"]


def test_labels_drop_marks_read_with_the_name_and_shrink_the_box():
    words = [{"text": "\u2018Isiro", "conf": 80, "col": 30, "row": 10, "w": 60, "h": 12},
             {"text": "{Juba,", "conf": 70, "col": 30, "row": 40, "w": 60, "h": 12}]
    lab = ng.labels(words)
    assert sorted(lab) == ["Isiro", "Juba"]
    assert abs(lab["Isiro"]["w"] - 50) < 1e-9 and abs(lab["Isiro"]["col"] - 35) < 1e-9
    assert abs(lab["Juba"]["w"] - 40) < 1e-9 and abs(lab["Juba"]["col"] - 30) < 1e-9


def test_labels_keep_the_most_confident_reading_of_each_name():
    words = [{"text": "Prizren", "conf": 70, "col": 1, "row": 1, "w": 5, "h": 5},
             {"text": "Prizren", "conf": 95, "col": 9, "row": 9, "w": 5, "h": 5},
             {"text": "Lipljan", "conf": 40, "col": 3, "row": 3, "w": 5, "h": 5},
             {"text": "x", "conf": 99, "col": 3, "row": 3, "w": 5, "h": 5}]
    lab = ng.labels(words, min_conf=60)
    assert list(lab) == ["Prizren"]
    assert lab["Prizren"]["col"] == 9


def synthetic(n_true=10, n_false=3, seed=1):
    """Names printed at z (complex, col - i row) for places at Z = a z + b, each with decoy candidates."""
    rnd = random.Random(seed)
    a = 180.0 * cmath.exp(1j * math.radians(3))
    b = complex(2.3e6, 5.2e6)
    z, cands = {}, {}
    for k in range(n_true):
        zz = complex(rnd.uniform(0, 1000), -rnd.uniform(0, 1200))
        z[f"T{k}"] = zz
        decoys = [complex(rnd.uniform(1e6, 4e6), rnd.uniform(4e6, 7e6)) for _ in range(2)]
        cands[f"T{k}"] = decoys + [a * zz + b]
    for k in range(n_false):
        z[f"F{k}"] = complex(rnd.uniform(0, 1000), -rnd.uniform(0, 1200))
        cands[f"F{k}"] = [complex(rnd.uniform(1e6, 4e6), rnd.uniform(4e6, 7e6)) for _ in range(3)]
    return a, b, z, cands


def test_fit_names_finds_the_similarity_among_decoys():
    a, b, z, cands = synthetic()
    fa, fb, inl = ng.fit_names(z, cands, diag=1560, tol_frac=0.02, iters=20000, seed=0)
    assert sorted(inl) == sorted(f"T{k}" for k in range(10))
    assert abs(fa - a) / abs(a) < 1e-6
    for n, Z in inl.items():
        assert abs(Z - (a * z[n] + b)) < 1e-3


def test_fit_names_rejects_rotations_beyond_the_limit():
    a, b, z, cands = synthetic()
    rot = cmath.exp(1j * math.radians(90))
    z90 = {n: v * rot for n, v in z.items()}  # the same map turned a quarter
    _, _, inl = ng.fit_names(z90, cands, diag=1560, tol_frac=0.02, iters=20000, seed=0, max_angle_deg=30)
    assert len(inl) <= 3


def test_anchor_picks_the_symbol_beside_the_label_nearest_the_prediction():
    label = {"col": 100, "row": 50, "w": 60, "h": 12}
    peaks = [{"col": 66, "row": 51, "score": 0.8},    # just left of the label: the town
             {"col": 140, "row": 50, "score": 0.9},   # just right, farther from the prediction
             {"col": 100, "row": 50, "score": 0.9},   # inside the label: a letter
             {"col": 300, "row": 300, "score": 0.9}]  # far away
    p = ng.anchor(label, peaks, predicted=(70, 55))
    assert (p["col"], p["row"]) == (66, 51)
    assert ng.anchor(label, peaks[2:], predicted=(70, 55)) is None


def test_robust_fit_drops_the_points_off_the_transform():
    rnd = random.Random(3)
    pts = []
    for k in range(12):
        c, r = rnd.uniform(0, 1000), rnd.uniform(0, 1200)
        pts.append({"name": f"P{k}", "col": c, "row": r, "x": 2.0e6 + 180 * c, "y": 5.0e6 - 180 * r})
    pts[3]["x"] += 180 * 25
    pts[7]["y"] -= 180 * 40
    kept, _ = ng.robust_fit(pts, "affine", tol_px=2.0)
    assert sorted(p["name"] for p in kept) == sorted(f"P{k}" for k in range(12) if k not in (3, 7))


def test_peaks_are_located_to_a_fraction_of_a_pixel():
    img = np.full((80, 80), 255, np.uint8)
    cv2.circle(img, (int(40.4 * 16), int(30.7 * 16)), 4 * 16, 0, 1, lineType=cv2.LINE_AA, shift=4)
    p = ng.symbol_peaks(ng.ring_score(img), [], min_score=0.5)
    assert len(p) == 1
    assert abs(p[0]["col"] - 40.4) < 0.25 and abs(p[0]["row"] - 30.7) < 0.25


def test_a_town_node_wins_over_its_boundary_nearby():
    hits = [{"lon": 21.00, "lat": 42.00, "category": "boundary", "type": "administrative"},
            {"lon": 21.01, "lat": 42.005, "category": "place", "type": "town"},
            {"lon": 25.0, "lat": 44.0, "category": "boundary", "type": "administrative"}]
    out = ng.merge_hits(hits)
    assert len(out) == 2
    assert (21.01, 42.005) in [(round(c["lon"], 3), round(c["lat"], 3)) for c in out]


def test_fit_symbols_picks_the_right_symbol_of_each_name():
    rnd = random.Random(5)
    a = 2900.0 * cmath.exp(1j * math.radians(2))
    b = complex(1.5e6, 0.5e6)
    places, options = {}, {}
    for k in range(12):
        s = complex(rnd.uniform(0, 1500), -rnd.uniform(0, 1060))
        places[f"N{k}"] = a * s + b
        # the town's ring and two other ring-like marks within reach of the label
        wrong = [s + complex(rnd.uniform(-30, 30), rnd.uniform(-30, 30)) for _ in range(2)]
        opts = wrong + [s]
        rnd.shuffle(opts)
        options[f"N{k}"] = opts
    places["X"] = complex(3e6, 3e6)  # a name whose place disagrees with the rest
    options["X"] = [complex(700, -500)]
    fa, fb, chosen = ng.fit_symbols(options, places, diag=1830, tol_px=3.0, iters=5000, seed=0)
    assert sorted(chosen) == sorted(f"N{k}" for k in range(12))
    for n, (s, q) in chosen.items():
        assert q == places[n]
        assert abs(fa * s + fb - places[n]) / abs(fa) < 1e-6


def test_fit_symbols_picks_the_right_place_among_several():
    a, b = 1000.0 + 0j, complex(1e6, 1e6)
    options = {f"N{k}": [complex(100 * k + 50, -(37 * k % 500) - 50)] for k in range(8)}
    rnd = random.Random(2)
    # the town, and a county centre some way off in a direction of its own
    places = {n: [a * o[0] + b, a * o[0] + b + 40e3 * cmath.exp(1j * rnd.uniform(0, 2 * math.pi))]
              for n, o in options.items()}
    fa, fb, chosen = ng.fit_symbols(options, places, diag=1000, tol_px=3.0, iters=3000, seed=1)
    assert len(chosen) == 8
    for n, (s, q) in chosen.items():
        assert q == places[n][0]


def test_names_in_capitals_are_areas_not_towns():
    assert not ng.is_town_label("EQUATEUR")
    assert not ng.is_town_label("NORTH MACEDONIA")
    assert ng.is_town_label("Kinshasa")
    assert ng.is_town_label("Novi Pazar")


def test_one_symbol_gives_one_control_point():
    pts = [{"name": "Kumanovo", "col": 10.0, "row": 20.0, "x": 1.0, "y": 2.0},
           {"name": "Kumanove", "col": 10.0, "row": 20.0, "x": 1.0, "y": 2.0},   # the same label misread
           {"name": "Tetovo", "col": 50.0, "row": 60.0, "x": 3.0, "y": 4.0}]
    out = ng.one_per_symbol(pts)
    assert len(out) == 2
    assert {p["name"] for p in out} >= {"Tetovo"}
