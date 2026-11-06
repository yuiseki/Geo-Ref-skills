# uvx --with numpy --with pypdfium2 --with pytest pytest scripts/test_deployment_geojson.py
import numpy as np

import deployment_geojson as G


def test_a_panel_that_passed_every_gate_is_used_everywhere():
    assert G.panel_use(set(), map_ok=True) == "global"


def test_a_panel_failing_only_on_spread_is_used_point_by_point():
    assert G.panel_use({"spread"}, map_ok=True) == "local"
    assert G.panel_use({"spread", "edge_uncertainty"}, map_ok=True) == "local"


def test_a_map_whose_answer_failed_on_spread_alone_still_gives_local_points():
    # the answer as a whole is dropped (the owner's choice, 2026-11-05) but points that pass the local checks are kept
    assert G.panel_use({"spread"}, map_ok=False) == "local"
    assert G.panel_use(set(), map_ok=False) == "local"


def test_a_panel_failing_on_residuals_is_never_used():
    assert G.panel_use({"loo_residual"}, map_ok=True) is None
    assert G.panel_use({"loo_residual", "spread"}, map_ok=False) is None


def test_a_local_point_must_lie_among_the_control_points():
    # 20 control points all west of 2.5 W; units at Tessalit and Kidal, outside them, came out 13 to 18 km (8 to 11 px) off
    # while their leave-one-out spread was 1.2 to 1.4 px: the jackknife does not see how a model bends away from the fit
    src = np.array([[0, 0], [100, 0], [100, 100], [0, 100], [50, 50]], float)
    assert G.inside_hull(src, 50, 50)
    assert G.inside_hull(src, 99, 1)
    assert not G.inside_hull(src, 150, 50)
    assert not G.inside_hull(src, 50, -5)


def test_the_nearest_text_is_a_capitalised_word_close_to_the_point():
    ws = [{"kind": "word", "text": "Bunia", "x": 100, "y": 100, "w": 20},
          {"kind": "word", "text": "road", "x": 101, "y": 100, "w": 10},
          {"kind": "word", "text": "Far", "x": 300, "y": 300, "w": 10},
          {"kind": "phrase", "text": "Bunia Town", "x": 100, "y": 100, "w": 40}]
    assert G.nearest_text(ws, 105, 105) == "Bunia"
    assert G.nearest_text(ws, 200, 200) is None


def test_a_point_just_outside_the_hull_within_the_pixel_tolerance_is_inside():
    # MONUSCO's inset of 2025: its control points are towns along one road, and the units at those towns sit on
    # their dots, 0.2 to 1.9 px from the control point read at the same town, outside the hull
    src = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert G.inside_hull(src, 102.0, 50.0, tol=3.0)
    assert not G.inside_hull(src, 104.0, 50.0, tol=3.0)
    assert not G.inside_hull(src, 102.0, 50.0)


def test_the_distance_to_a_thin_hull_is_to_its_nearest_edge():
    # a point 2 px beside a long thin hull is behind the line of a far edge too, by much more
    src = [[0, 0], [10, 300], [12, 600], [4, 300]]
    assert G.inside_hull(src, 2.0, 302.0, tol=3.0) or G.inside_hull(src, 1.0, 301.0, tol=3.0)
    assert G.inside_hull(src, 13.0, 598.0, tol=3.0)
    assert not G.inside_hull(src, 30.0, 300.0, tol=3.0)


def write_run(tmp_path, answers):
    """A run directory with one rendered candidate and, per (key, passed gates), an answer and its gates."""
    import json
    (tmp_path / "cands").mkdir()
    (tmp_path / "cands/candidates.json").write_text(json.dumps({"candidates": [
        {"dpi": 144, "from": {"kind": "rendered", "box_px": [0, 0, 100, 100]}}]}))
    for key, method, failed in answers:
        gcps = [{"col": c, "row": r, "lon": 30 + c / 1000, "lat": 10 - r / 1000} for c in (0, 50, 100) for r in (0, 50, 100)]
        (tmp_path / f"answer.c1.{key}.json").write_text(json.dumps({"image": {"width": 100, "height": 100},
                                                                       "method": method, "gcps": gcps}))
        (tmp_path / f"gates.c1.{key}.json").write_text(json.dumps({"gates": [{"name": n, "passed": False} for n in failed]
                                                                     + [{"name": "geometry", "passed": True}]}))
    return tmp_path


def test_of_a_candidates_answers_the_one_that_passed_is_used(tmp_path):
    # UNDOF: the town names' answer failed on spread (it may be used locally); the graticule's passed every gate
    run = write_run(tmp_path, [("affine", "affine", ["spread"]), ("grid_affine", "affine", [])])
    (p,) = G.panels_of(run, True)
    assert not p["local"] and p["method"] == "affine"


def test_a_failed_answer_with_no_points_is_not_read(tmp_path):
    import json
    run = write_run(tmp_path, [("affine", "affine", ["spread"])])
    (run / "answer.c1.grid_affine.json").write_text(json.dumps({"status": "failed", "reason": "no grid"}))
    (p,) = G.panels_of(run, False)
    assert p["local"]


def test_the_distance_to_the_hull_is_zero_inside_and_to_the_nearest_edge_outside():
    src = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert G.hull_distance(src, 50, 50) == 0.0
    assert G.hull_distance(src, 100, 40) == 0.0  # on an edge
    assert abs(G.hull_distance(src, 130, 50) - 30.0) < 1e-9
    assert abs(G.hull_distance(src, 103, 104) - 5.0) < 1e-9  # nearest to a corner


def stack_at(x, y, n=1):
    return {"stack": 1, "located_by": "leader", "location": {"x": x, "y": y},
            "units": [{"label": "", "inner": "", "signature": "s", "arm": None, "echelon": None, "size_marks": []}] * n}


def global_panel():
    """A panel that passed every gate: control points over a 100 x 100 px square of a 1000 x 1000 px image, 72 dpi."""
    wm, tf = G.wm, G.tf
    src = np.array([[400, 400], [500, 400], [500, 500], [400, 500], [450, 450]], float)
    dst = np.array([wm.lonlat_to_mercator(30 + (c - 400) / 1000, 10 - (r - 400) / 1000) for c, r in src])
    return {"cand": 1, "local": False, "src": src, "dst": dst, "method": "affine", "k": 1.0, "o": [0, 0], "W": 1000,
            "H": 1000, "model": tf.fit("affine", src, dst), "area": 1000 * 1000}


def test_a_unit_far_outside_the_control_points_of_a_map_that_passed_is_not_used():
    # MONUSCO 2016-08-09: a stack in the corner of the sheet, where the map has no towns, came out in the Atlantic
    # (9.9 E, 11.9 S) on a map whose answer passed every gate: extrapolation, not a position
    P = global_panel()
    size = 100.0  # the control points' larger side in pixels
    far = G.GLOBAL_HULL_MARGIN * size + 10
    feats, n, why = G.features_of({"stacks": [stack_at(500 + far, 450)]}, [P], [], "M", "20160809", True)
    assert feats == [] and why["outside_hull"] == 1


def test_a_unit_just_outside_the_control_points_of_a_map_that_passed_is_used():
    # units at the edge of the sheet's towns are real; the margin keeps them
    P = global_panel()
    near = G.GLOBAL_HULL_MARGIN * 100.0 - 10
    feats, n, why = G.features_of({"stacks": [stack_at(500 + near, 450)]}, [P], [], "M", "20160809", True)
    assert len(feats) == 1 and why["outside_hull"] == 0


def test_a_unit_inside_the_control_points_is_used():
    feats, n, why = G.features_of({"stacks": [stack_at(450, 450, 3)]}, [global_panel()], [], "M", "20160809", True)
    assert len(feats) == 3 and why["outside_hull"] == 0
