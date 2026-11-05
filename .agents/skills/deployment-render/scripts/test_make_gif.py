# uvx --with numpy --with opencv-python-headless --with cairosvg --with pillow --with pytest pytest scripts/test_make_gif.py
import make_gif as mg


def doc(date, n=1, ok=True, key="date"):
    fs = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
           "properties": {"date": date, "map_ok": ok}} for _ in range(n)]
    d = {"type": "FeatureCollection", "features": fs}
    if key == "map_date":
        d["map_date"] = date
    return d


def test_frames_are_in_date_order_and_a_date_is_kept_once():
    f = mg.frames_of([doc("20250509"), doc("20240101"), doc("20250509", 2), doc("20230101", 0)])
    assert [d for d, _ in f] == ["20240101", "20250509"] and len(f[1][1]) == 1


def test_the_collection_date_wins():
    assert mg.map_date({"map_date": "20200101", "features": [{"properties": {"date": "x"}}]}) == "20200101"


def test_caption_has_the_date_and_flags_a_map_that_did_not_pass():
    assert mg.caption("20250509", doc("20250509", 3)["features"]) == "2025-05-09   3 units drawn"
    assert "one by one" in mg.caption("20220202", doc("20220202", 2, ok=False)["features"])
