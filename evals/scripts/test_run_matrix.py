# uvx --with pytest pytest scripts/test_run_matrix.py
import run_matrix


def test_classify_all_four_outcomes():
    assert run_matrix.classify(False, True, 0.2, 1.0) == "ok"
    assert run_matrix.classify(False, True, 5.0, 1.0) == "gate_hole"
    assert run_matrix.classify(False, False, 0.2, 1.0) == "over_strict"
    assert run_matrix.classify(False, False, 5.0, 1.0) == "refused"
    assert run_matrix.classify(True, False, None, 1.0) == "refused"


def test_gates_passed_without_a_score_is_a_hole():
    assert run_matrix.classify(False, True, None, 1.0) == "gate_hole"


def test_task_grid_is_the_full_product_with_unique_ids():
    m = {"level": 1, "places": {"a": [0, 0], "b": [1, 1]}, "styles": ["s"], "kinds": ["similarity", "affine"],
         "strengths": [0.25, 1.0], "seeds": [1, 2, 3]}
    ts = list(run_matrix.tasks(m))
    assert len(ts) == 2 * 1 * 2 * 2 * 3
    assert len({t["id"] for t in ts}) == len(ts)


def test_negative_controls_move_the_hint_to_another_place():
    m = {"level": 1, "places": {"a": [10.0, 20.0], "b": [30.0, 40.0]}, "styles": ["s"],
         "negatives": {"pairs": [["a", "b"]], "kinds": ["projective"], "strengths": [0.5], "seeds": [1, 2]}}
    ns = list(run_matrix.negatives(m))
    assert len(ns) == 2
    assert ns[0]["center"] == [10.0, 20.0] and ns[0]["wrong_center"] == [30.0, 40.0]
    assert run_matrix.shifted_bbox([9.0, 19.5, 11.0, 20.5], [30.0, 40.0]) == [29.0, 39.5, 31.0, 40.5]
    assert list(run_matrix.negatives({"level": 1})) == []
