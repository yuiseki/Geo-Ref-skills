# uvx --with numpy --with pytest pytest scripts/test_run_doc_matrix.py
import run_doc_matrix as rdm


def test_embedded_images_become_candidates_with_their_own_dpi_largest_area_first():
    man = {"images": [
        {"file": "p001-i001.png", "px": [1240, 1754], "page": 1, "page_size_pt": [595, 842], "bbox_pt": [0, 0, 595, 842]},
        {"file": "p001-i002.png", "px": [900, 700], "page": 1, "page_size_pt": [595, 842], "bbox_pt": [100, 200, 550, 550]},
        {"file": "p001-i003.png", "px": [10, 10], "page": 1, "page_size_pt": [595, 842], "bbox_pt": [0, 0, 5, 5]},
        {"file": "p001-i004.png", "px": [100, 100], "page": 1, "in_form": True}]}
    c = rdm.embedded_candidates(man, min_px=64)
    assert [x["file"] for x in c] == ["p001-i001.png", "p001-i002.png"]
    m = c[1]
    assert m["dpi"] == 900 * 72 / 450
    # top left in page pixels at that dpi: x 100 pt, y from the top 842 - 550 = 292 pt
    assert m["box"] == [100 * m["dpi"] / 72, 292 * m["dpi"] / 72, 550 * m["dpi"] / 72, 642 * m["dpi"] / 72]


def test_page_candidates_keep_their_rank():
    cands = [{"box": [10, 20, 110, 220], "score": 0.5}, {"box": [0, 0, 50, 50], "score": 0.1}]
    c = rdm.page_candidates(cands, dpi=150, max_n=1)
    assert c == [{"box": [10, 20, 110, 220], "dpi": 150, "score": 0.5}]


def test_next_candidate_only_after_a_declared_failure():
    assert rdm.try_next({"outcome": "refused", "failed_gates": "place_hint"})
    assert rdm.try_next({"outcome": "refused", "register": "failed"})
    assert not rdm.try_next({"outcome": "refused", "register": "ok", "failed_gates": "spread"})
    assert not rdm.try_next({"outcome": "ok"})
    assert not rdm.try_next({"outcome": "gate_hole"})
