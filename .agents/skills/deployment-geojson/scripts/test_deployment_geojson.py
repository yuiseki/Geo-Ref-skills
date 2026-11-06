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
