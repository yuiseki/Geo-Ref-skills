# uvx --with pytest pytest scripts/test_eval_real_find.py
import eval_real_find as erf

MAP = {"page": 1, "bbox_pt": [100, 100, 500, 500]}


def cand(page, box):
    return {"page": page, "bbox_pt": box}


def test_a_part_of_the_map_counts_but_a_box_that_is_mostly_paper_does_not():
    assert erf.hit(cand(1, [100, 100, 400, 400]), [MAP])  # the map's core, 56% of it, all map
    assert not erf.hit(cand(1, [0, 0, 600, 900]), [MAP])  # holds the map but is mostly not map
    assert not erf.hit(cand(1, [100, 100, 150, 150]), [MAP])  # all map, but a sliver of it
    assert not erf.hit(cand(2, [100, 100, 500, 500]), [MAP])  # right place, wrong page


def test_rank_is_the_first_candidate_on_any_map():
    other = {"page": 2, "bbox_pt": [0, 0, 100, 100]}
    cands = [cand(1, [600, 600, 700, 700]), cand(2, [0, 0, 100, 100]), cand(1, [100, 100, 500, 500])]
    row = erf.score_doc(cands, [MAP, other])
    assert row["rank"] == 2 and row["n"] == 3


def test_a_document_without_a_map_has_no_rank_and_says_so():
    row = erf.score_doc([cand(1, [0, 0, 10, 10])], [])
    assert row["rank"] == 0 and row["no_map"]


def test_candidates_without_a_place_on_the_page_never_hit():
    assert not erf.hit({"px": [10, 10]}, [MAP])


def test_a_small_part_of_a_map_is_counted_apart_from_a_wrong_thing():
    cands = [cand(1, [600, 600, 700, 700]), cand(1, [100, 100, 150, 150]), cand(1, [100, 100, 500, 500])]
    row = erf.score_doc(cands, [MAP])
    assert row["rank"] == 3 and row["rank_part"] == 2  # the sliver is all map, but too little of it
