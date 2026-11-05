# uvx --with pytest pytest scripts/test_batch.py
import batch as B


def test_the_mission_is_the_first_acronym_found_whole_in_the_title_then_the_name():
    assert B.mission_of("MONUSCO 7777 R60 Jun25 120%", "x") == "MONUSCO"
    assert B.mission_of("Map", "UNFICYP_2930_R100") == "UNFICYP"
    assert B.mission_of("monusco map") == "MONUSCO"
    assert B.mission_of("UNMISSING map") is None  # whole words only, not a prefix
    assert B.mission_of(None, "") is None


def test_the_date_is_the_creation_date_else_the_modification_date():
    assert B.pdf_date("D:20250601120000+00'00'", "D:20260101") == "20250601"
    assert B.pdf_date(None, "D:20190628") == "20190628"
    assert B.pdf_date("garbage", None) == "00000000"


def test_every_vector_frame_among_the_first_eight_is_tried_besides_the_first_three():
    cs = [{"from": {}} for _ in range(10)]
    cs[5]["from"]["frame"] = True
    cs[9]["from"]["frame"] = True  # beyond the first eight
    cs[1]["from"]["frame"] = True
    assert B.to_try(cs) == [0, 1, 2, 5]


def test_each_mission_lists_country_codes_and_no_map_number():
    import re
    for m, cc in B.MISSIONS.items():
        assert re.fullmatch(r"[a-z]{2}(,[a-z]{2})*", cc), m
        assert not re.search(r"\d", m), m


def test_after_a_pass_the_first_four_and_every_frame_are_tried_for_insets():
    cs = [{"from": {}} for _ in range(12)]
    cs[10]["from"]["frame"] = True
    assert B.to_try(cs, first=4, total=len(cs)) == [0, 1, 2, 3, 10]
