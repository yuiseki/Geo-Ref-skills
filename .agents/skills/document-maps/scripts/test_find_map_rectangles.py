# uvx --with numpy --with opencv-python-headless --with pytest pytest scripts/test_find_map_rectangles.py
import cv2
import numpy as np
import pytest

import find_map_rectangles as fm


def map_like(w, h, seed=0):
    g = np.random.default_rng(seed)
    img = np.full((h, w, 3), (233, 239, 242), np.uint8)
    for _ in range(25):
        c = tuple(int(v) for v in g.integers(0, [w, h]))
        cv2.circle(img, c, int(g.integers(10, 40)), (201, 208, 217), -1)
    cv2.polylines(img, [np.array([[0, h // 3], [w // 2, h // 2], [w, h // 3]], np.int32)], False, (223, 211, 170), 18)
    for _ in range(40):
        a = tuple(int(v) for v in g.integers(0, [w, h]))
        b = tuple(int(v) for v in g.integers(0, [w, h]))
        cv2.line(img, a, b, (120, 200, 250) if g.random() < 0.3 else (255, 255, 255), int(g.integers(2, 6)))
    return img


def page(with_frame=True):
    p = np.full((1754, 1240, 3), 255, np.uint8)
    for i in range(12):  # body text: thin rows of small dark marks
        y = 120 + i * 28
        for x in range(100, 1100, 22):
            cv2.rectangle(p, (x, y), (x + 14, y + 12), (40, 40, 40), -1)
    p[600:1100, 150:1050] = map_like(900, 500)
    if with_frame:
        cv2.rectangle(p, (148, 598), (1051, 1101), (0, 0, 0), 2)
    for i, hgt in enumerate([120, 200, 80, 160]):  # a bar chart
        cv2.rectangle(p, (200 + i * 90, 1600 - hgt), (260 + i * 90, 1600), (180, 120, 60), -1)
    return p


def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / (area(a) + area(b) - inter)


@pytest.mark.parametrize("framed", [True, False])
def test_the_map_is_a_candidate_and_ranks_first(framed):
    cands = fm.find(page(framed))
    assert cands, "no candidates"
    best = cands[0]
    assert iou(best["box"], (150, 600, 1050, 1100)) > 0.9, cands[:3]


def test_text_and_a_small_chart_are_not_ranked_above_the_map():
    cands = fm.find(page())
    boxes = [c["box"] for c in cands]
    i_map = next(i for i, b in enumerate(boxes) if iou(b, (150, 600, 1050, 1100)) > 0.9)
    assert i_map == 0
    assert all("score" in c and "features" in c for c in cands)


def test_a_blank_page_has_no_candidates():
    assert fm.find(np.full((800, 600, 3), 255, np.uint8)) == []


def photo_like(w, h, seed=1):
    """Smooth shading and sensor noise: many colours, gradients every way, but no flat fills."""
    g = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 3), np.float32)
    for c in range(3):
        for _ in range(4):
            cx, cy, s = g.uniform(0, w), g.uniform(0, h), g.uniform(60, 200)
            img[..., c] += g.uniform(40, 120) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s))
    img += g.normal(0, 12, img.shape)
    img = cv2.GaussianBlur(img, (0, 0), 1.2)
    return np.clip(img + 40, 0, 235).astype(np.uint8)


def test_a_photo_the_size_of_the_map_does_not_outrank_it():
    p = np.full((1754, 1240, 3), 255, np.uint8)
    p[150:650, 150:1050] = photo_like(900, 500)
    p[900:1400, 150:1050] = map_like(900, 500)
    cands = fm.find(p)
    assert iou(cands[0]["box"], (150, 900, 1050, 1400)) > 0.9, [(c["box"], round(c["score"], 3)) for c in cands]


def scanned(p, seed=2):
    """A page through a scanner: off-white paper, noise, JPEG."""
    g = np.random.default_rng(seed)
    paper = np.array((228, 234, 238), np.float32)  # BGR, yellowish
    out = p.astype(np.float32) * (paper / 255.0) + g.normal(0, 4, p.shape)
    ok, buf = cv2.imencode(".jpg", np.clip(out, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 75])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


@pytest.mark.parametrize("framed", [True, False])
def test_a_scanned_page_on_off_white_paper(framed):
    cands = fm.find(scanned(page(framed)))
    assert iou(cands[0]["box"], (150, 600, 1050, 1100)) > 0.9, [(c["box"], round(c["score"], 3)) for c in cands[:3]]


def test_two_maps_side_by_side_are_two_candidates():
    p = np.full((1754, 1240, 3), 255, np.uint8)
    p[600:1100, 100:580] = map_like(480, 500, seed=3)
    p[600:1100, 640:1120] = map_like(480, 500, seed=4)
    boxes = [c["box"] for c in fm.find(p)[:2]]
    for want in [(100, 600, 580, 1100), (640, 600, 1120, 1100)]:
        assert any(iou(b, want) > 0.9 for b in boxes), boxes


def test_a_chart_touching_the_map_does_not_widen_it():
    p = np.full((1754, 1240, 3), 255, np.uint8)
    p[600:1100, 200:950] = map_like(750, 500, seed=5)
    for i, hgt in enumerate([180, 200, 130]):  # bars that start on the map's bottom edge, one sticking out left
        x = 170 + i * 85
        cv2.rectangle(p, (x, 1100), (x + 60, 1100 + hgt), (180, 120, 60), -1)
    cv2.rectangle(p, (200, 585), (700, 599), (40, 40, 40), -1)  # a caption line touching the top
    cands = fm.find(p)
    assert iou(cands[0]["box"], (200, 600, 950, 1100)) > 0.9, [(c["box"], c["kind"], round(c["score"], 3)) for c in cands[:4]]


def test_largest_filled_rectangle():
    m = np.zeros((6, 8), bool)
    m[1:5, 2:7] = True
    m[0, 0:8] = True
    assert fm.largest_filled_rectangle(m) == (2, 0, 7, 5)  # row 0 extends the block upwards
    assert fm.largest_filled_rectangle(np.zeros((3, 3), bool)) is None


def test_a_legend_box_inside_the_map_corner_does_not_shrink_it():
    p = np.full((1754, 1240, 3), 255, np.uint8)
    p[600:1100, 200:950] = map_like(750, 500, seed=6)
    cv2.rectangle(p, (720, 960), (940, 1090), (255, 255, 255), -1)  # white legend box, 10 px in from the corner
    cv2.rectangle(p, (720, 960), (940, 1090), (0, 0, 0), 2)
    for k, c in enumerate([(60, 80, 220), (200, 130, 70), (90, 170, 90)]):
        cv2.rectangle(p, (735, 975 + k * 38), (760, 995 + k * 38), c, -1)
        cv2.rectangle(p, (770, 980 + k * 38), (920, 990 + k * 38), (60, 60, 60), -1)
    cands = fm.find(p)
    assert iou(cands[0]["box"], (200, 600, 950, 1100)) > 0.9, [(c["box"], c["kind"], round(c["score"], 3)) for c in cands[:4]]


def test_fill_holes_fills_only_what_is_enclosed():
    m = np.zeros((7, 9), bool)
    m[1:6, 1:6] = True
    m[2:4, 2:4] = False  # enclosed
    m[4:6, 4:6] = False  # open to the outside through the right edge? no: column 6 is blank, so it is open
    f = fm.fill_holes(m)
    assert f[2:4, 2:4].all() and not f[4:6, 4:6].any() and not f[:, 7:].any()


def test_a_dark_photograph_makes_no_frame():
    p = np.full((1754, 1240, 3), 255, np.uint8)
    ph = photo_like(500, 400, seed=7)
    p[700:1100, 600:1100] = (ph * 0.4).astype(np.uint8)  # dark all over: no thin lines in it
    assert all(c["kind"] != "frame" for c in fm.find(p)), [(c["box"], c["kind"]) for c in fm.find(p)]


@pytest.mark.parametrize("gap", [12, 24])
def test_a_panel_of_four_maps_with_a_narrow_gap_gives_each_map(gap):
    p = np.full((1754, 1240, 3), 255, np.uint8)
    want = []
    for r in range(2):
        for c in range(2):
            x0, y0 = 120 + c * (480 + gap), 500 + r * (400 + gap)
            p[y0:y0 + 400, x0:x0 + 480] = map_like(480, 400, seed=10 + 2 * r + c)
            want.append((x0, y0, x0 + 480, y0 + 400))
    cands = fm.find(p)
    import json
    json.dumps(cands)  # candidates.json is written from these
    boxes = [c["box"] for c in cands]
    for w in want:
        assert any(iou(b, w) > 0.9 for b in boxes), (w, boxes)


def test_xy_cut():
    m = np.zeros((40, 50), bool)
    m[2:18, 2:23] = m[2:18, 27:48] = m[22:38, 2:48] = True
    got = sorted(fm.xy_cut(m, min_side=5))
    assert got == sorted([(2, 2, 23, 18), (27, 2, 48, 18), (2, 22, 48, 38)])
    assert fm.xy_cut(np.ones((20, 20), bool)) == []


def sparse_map_like(w, h, seed=0):
    """Black labels and a few thin lines on white, like a binarised map: little ink, gaps wider than a word."""
    g = np.random.default_rng(seed)
    img = np.full((h, w, 3), 255, np.uint8)
    for _ in range(int(w * h / 4000)):
        x, y = int(g.integers(0, w - 60)), int(g.integers(0, h - 12))
        ang = float(g.choice([0, 0, 0, 30, -30, 60, 90]))
        box = cv2.boxPoints(((x + 25, y + 5), (int(g.integers(20, 55)), 7), ang)).astype(np.int32)
        cv2.fillPoly(img, [box], (0, 0, 0))
    for _ in range(4):
        a = tuple(int(v) for v in g.integers(0, [w, h]))
        b = tuple(int(v) for v in g.integers(0, [w, h]))
        cv2.line(img, a, b, (0, 0, 0), 3)
    for x in (0, w - 1):  # labels reach the edges, as a cropped map's do
        for y in range(10, h - 10, 60):
            cv2.rectangle(img, (max(0, x - 20), y), (min(w - 1, x + 20), y + 6), (0, 0, 0), -1)
    for y in (0, h - 1):
        for x in range(10, w - 10, 70):
            cv2.rectangle(img, (x, max(0, y - 6)), (x + 30, min(h - 1, y + 6)), (0, 0, 0), -1)
    return img


@pytest.mark.xfail(strict=True, reason="known limit (2026-11-04): an unframed map of labels on white paper is "
                   "the same colour as the paper between its labels; closing at 1.2 % or 3 % of the page leaves it "
                   "in pieces")
def test_a_sparse_binary_map_is_one_candidate_in_the_top_three():
    p = page(with_frame=False)
    p[600:1100, 150:1050] = sparse_map_like(900, 500, seed=8)
    boxes = [c["box"] for c in fm.find(p)[:3]]
    assert any(iou(b, (150, 600, 1050, 1100)) > 0.9 for b in boxes), boxes


def test_a_text_block_on_a_coloured_box_scores_below_a_map_of_its_size():
    box = np.full((500, 900, 3), (200, 230, 245), np.uint8)  # a beige panel
    for i in range(14):
        y = 20 + i * 34
        for x in range(20, 880, 26):
            cv2.rectangle(box, (x, y), (x + 18, y + 14), (40, 40, 120), -1)
    s_text, f_text = fm.appearance(box)
    s_map, f_map = fm.appearance(map_like(900, 500))
    assert f_text["gaps"] > 0.3 and f_map["gaps"] < 0.05
    assert s_map > s_text
