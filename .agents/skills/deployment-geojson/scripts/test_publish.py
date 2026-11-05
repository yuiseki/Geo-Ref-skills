# uvx --with pytest pytest scripts/test_publish.py
import json

import pytest

import publish as P

# a made-up map number, 7777
SRC = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.2, 1.5]},
       "properties": {"mission": "MONUSCO", "map": "MONUSCO_7777_R60", "title": "MONUSCO 7777 R60 Jun25 120%", "date": "20250601",
                      "label": "BANGLADESH", "inner": None, "symbol": "d6", "arm": "infantry", "echelon": "battalion",
                      "size_marks": ["bar", "bar"], "nearest_text": "Bunia", "stack": 3, "located_by": "leader", "panel": 2,
                      "panel_local": False, "map_ok": True, "std_px": 0.4}}
META = dict(sha256="ab" * 32, commit="c0ffee" * 6 + "c0ff", date="20250601", mission="MONUSCO", references=["7777"])


def test_no_reference_number_or_title_survives_and_the_provenance_is_added():
    fc = P.publishable([SRC], **META)
    p = fc["features"][0]["properties"]
    assert "map" not in p and "title" not in p and "panel" not in p
    assert p["mission"] == "MONUSCO" and p["date"] == "20250601" and p["label"] == "BANGLADESH"
    assert fc["source_sha256"] == META["sha256"] and fc["tool_commit"] == META["commit"]
    assert fc["based_on"] == "Based on United Nations map" and fc["map_date"] == "20250601"
    assert "ABSOLUTELY NO WARRANTY" in fc["disclaimer"] and "may be wrong" in fc["disclaimer"]
    assert "may be wrong" in p["no_warranty"]  # survives when one feature is copied out alone
    assert "7777" not in json.dumps(fc)


def test_a_reference_number_hiding_in_a_value_stops_the_export():
    bad = json.loads(json.dumps(SRC))
    bad["properties"]["label"] = "see 7777 R60"
    with pytest.raises(ValueError):
        P.publishable([bad], **META)


def test_a_date_that_contains_the_digits_of_a_reference_is_not_a_reference():
    # whole runs only: 20250601 is not 2506
    assert P.publishable([SRC], **{**META, "references": ["2506"]})["features"]


def test_reference_numbers_are_the_four_or_five_digit_runs_of_a_name():
    assert P.reference_numbers("MONUSCO_7777_R60", "MONUSCO 7777 R60 Jun25 120%") == ["7777"]
    assert P.reference_numbers("1234_Rev-_100") == ["1234"]
    assert P.reference_numbers(None, "UNFICYP R100") == []


def test_the_file_name_carries_mission_date_and_hash_not_the_reference():
    assert P.out_name("MONUSCO", "20250601", "ab" * 32) == "MONUSCO_20250601_abababababab.geojson"
    assert P.out_name(None, "20250601", "cd" * 32).startswith("UNKNOWN_")
