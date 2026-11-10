# uvx --with numpy --with opencv-python-headless --with pillow --with pypdfium2==5.14.0 --with scikit-image --with pytest pytest scripts/test_eval_find.py
import pytest

import eval_find


def test_iou_of_a_box_with_itself_is_one_and_with_a_disjoint_box_zero():
    a = [0, 0, 10, 10]
    assert eval_find.iou(a, a) == 1.0
    assert eval_find.iou(a, [20, 20, 30, 30]) == 0.0
    assert eval_find.iou(a, [5, 0, 15, 10]) == pytest.approx(50 / 150)


def test_score_gives_the_first_candidate_that_covers_the_map():
    truth = [0, 0, 100, 100]
    boxes = [[0, 0, 50, 50], [1, 1, 100, 100], [0, 0, 100, 100]]
    rank, v = eval_find.score(boxes, truth)
    assert rank == 2 and v >= 0.9


def test_score_without_a_match_gives_rank_zero_and_the_best_iou():
    rank, v = eval_find.score([[0, 0, 50, 50], [0, 0, 50, 100]], [0, 0, 100, 100])
    assert rank == 0 and v == pytest.approx(0.5)
    assert eval_find.score([], [0, 0, 1, 1]) == (0, 0.0)
