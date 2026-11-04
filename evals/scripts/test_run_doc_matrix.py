# uvx --with numpy --with pytest pytest scripts/test_run_doc_matrix.py
import run_doc_matrix as rdm


def test_next_candidate_only_after_a_declared_failure():
    assert rdm.try_next({"outcome": "refused", "failed_gates": "place_hint"})
    assert rdm.try_next({"outcome": "refused", "register": "failed"})
    assert not rdm.try_next({"outcome": "refused", "register": "ok", "failed_gates": "spread"})
    assert not rdm.try_next({"outcome": "ok"})
    assert not rdm.try_next({"outcome": "gate_hole"})


def test_a_candidate_box_in_page_pixels_at_its_own_dpi():
    c = {"dpi": 144.0, "bbox_pt": [100, 300, 400, 500], "px": [600, 400]}
    k = 2.0
    assert rdm.candidate_box(c, page_h_pt=842) == [100 * k, (842 - 500) * k, 400 * k, (842 - 300) * k]
    assert rdm.candidate_box({"px": [10, 10]}, page_h_pt=842) is None  # no place on the page
