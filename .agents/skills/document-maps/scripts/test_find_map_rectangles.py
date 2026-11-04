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
