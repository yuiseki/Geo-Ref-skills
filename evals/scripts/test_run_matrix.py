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


def test_photometrics_are_an_axis_and_default_to_none():
    m = {"level": 2, "places": {"a": [0, 0]}, "styles": ["s"], "kinds": ["similarity"], "strengths": [0.5], "seeds": [1]}
    assert [t["photometric"] for t in run_matrix.tasks(m)] == ["none"]
    m["photometrics"] = ["none", "gray", "binary"]
    ts = list(run_matrix.tasks(m))
    assert [t["photometric"] for t in ts] == ["none", "gray", "binary"]
    assert len({t["id"] for t in ts}) == 3


def test_attempts_from_either_form():
    assert run_matrix.attempts({}) == [{"registrar": "feature-registration", "args": []}]
    m = {"registrars": ["feature-registration", "cross-style-registration"],
         "registrar_args": {"cross-style-registration": ["--mask", "lines"]}}
    assert run_matrix.attempts(m)[1] == {"registrar": "cross-style-registration", "args": ["--mask", "lines"]}
    a = [{"registrar": "cross-style-registration", "ref_style": "roads-minimal", "args": ["--mask", "lines"]}]
    assert run_matrix.attempts({"attempts": a}) == a


def test_zooms_are_an_axis_when_given():
    m = {"level": 4, "zoom": 15, "places": {"a": [0, 0]}, "styles": ["s"], "kinds": ["similarity"], "strengths": [0.5],
         "seeds": [1]}
    assert [t["zoom"] for t in run_matrix.tasks(m)] == [15]
    m["zooms"] = [14, 16]
    ts = list(run_matrix.tasks(m))
    assert [t["zoom"] for t in ts] == [14, 16] and len({t["id"] for t in ts}) == 2


def test_level4_hint_comes_from_place_hint_scale_or_is_a_refusal():
    ok = {"status": "ok", "bbox": [1, 2, 3, 4], "scale": {"status": "ok", "bbox": [1.5, 2.5, 2.5, 3.5], "zoom": 16}}
    assert run_matrix.hint_from_place_hint(ok) == {"bbox": [1.5, 2.5, 2.5, 3.5], "zoom": 16, "source": "place-hint"}
    no_scale = {"status": "ok", "bbox": [1, 2, 3, 4], "scale": {"status": "failed", "reason": "2 of 3 names"}}
    assert run_matrix.hint_from_place_hint(no_scale) is None
    assert run_matrix.hint_from_place_hint({"status": "failed", "reason": "support 1"}) is None
