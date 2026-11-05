# uvx --with numpy --with pypdfium2 --with pytest pytest scripts/test_road_geojson.py
import numpy as np

import road_geojson as rg
import transforms as tf
import webmercator as wm


def panel(k=2.0, o=(10, 20)):
    # pixel (c, r) of the panel -> mercator: 1 px = 1000 m east, 1000 m south, from (3.0e6, 1.0e6)
    src = np.array([[0, 0], [100, 0], [0, 100], [100, 100]], float)
    dst = np.array([[3.0e6 + c * 1000, 1.0e6 - r * 1000] for c, r in src])
    return {"k": k, "o": o, "W": 100, "H": 100, "model": tf.fit("affine", src, dst)}


def test_dates_come_from_the_file_name():
    assert rg.date_of("x__SSD_LC_OP_AccessConstraints_A3L_20260109.pdf") == "2026-01-09"
    assert rg.date_of("x__ssdlcopaccessconstraintsa3l_20260410.pdf") == "2026-04-10"
    assert rg.date_of("south-sudan-access-constraints-map-4-september-2026__South Sudan  Access Constraints Map 04 September 2026.pdf") == "2026-09-04"


def test_a_line_goes_from_page_points_to_longitude_and_latitude():
    P = panel()
    # page point (x, y) -> panel pixel (2x - 10, 2y - 20)
    (g,) = rg.geometry([[(5, 10), (55, 10)]], P, [])
    lon, lat = wm.mercator_to_lonlat(3.0e6, 1.0e6)
    assert g["type"] == "LineString"
    assert np.allclose(g["coordinates"][0], [lon, lat], atol=1e-5)
    lon2, _ = wm.mercator_to_lonlat(3.0e6 + 100 * 1000, 1.0e6)
    assert np.allclose(g["coordinates"][1][0], lon2, atol=1e-5)


def test_points_outside_the_panel_or_inside_an_inset_frame_are_cut_off():
    P = panel()
    inset = (40, 0, 80, 60)  # in the rendering's pixels, as candidate boxes are
    # pixels along y = 30: c = 0, 20, 50 (in the inset), 60 (in the inset), 90, 120 (outside the panel)
    pts = [(5, 25), (15, 25), (30, 25), (35, 25), (50, 25), (65, 25)]
    (g,) = rg.geometry([pts], P, [inset])
    assert g["type"] == "LineString" and len(g["coordinates"]) == 2  # (0, 20) only; 90 alone is dropped
    pts2 = [(5, 25), (15, 25), (30, 25), (50, 25), (55, 25)]  # the inset cuts the line in two
    (g2,) = rg.geometry([pts2], P, [inset])
    assert g2["type"] == "MultiLineString" and [len(x) for x in g2["coordinates"]] == [2, 2]
    assert rg.geometry([[(30, 25), (35, 25)]], P, [inset]) == []


def test_labels_are_used_only_where_lines_and_table_agree():
    ok = [{"ids": ["A"], "agrees": True}] * 40 + [{"ids": ["B"], "agrees": False}] + [{"ids": [], "agrees": None}] * 9
    bad = [{"ids": ["A"], "agrees": True}] * 40 + [{"ids": ["B"], "agrees": False}] * 10
    assert rg.labels_reliable(ok) and not rg.labels_reliable(bad)


def test_rectangles_found_inside_the_map_frame_are_cut_whether_vector_frames_or_not(tmp_path):
    # January 2026: the Koch inset was found on the rendered page, not as a vector frame (candidate 8)
    import json
    run = tmp_path / "run"
    (run / "cands").mkdir(parents=True)
    cands = [{"dpi": 150, "from": {"kind": "rendered", "box_px": [58, 2, 1013, 671], "frame": True}},
             {"dpi": 150, "from": {"kind": "rendered", "box_px": [60, 533, 256, 619], "frame": True}},
             {"dpi": 4000, "from": {"kind": "image", "box_px": [0, 0, 515, 455]}},
             {"dpi": 150, "from": {"kind": "rendered", "box_px": [968, 406, 1115, 673]}},  # the table, beyond the frame
             {"dpi": 150, "from": {"kind": "rendered", "box_px": [461, 14, 646, 268]}}]
    (run / "cands/candidates.json").write_text(json.dumps({"candidates": cands}))
    gcps = [{"col": c, "row": r, "lon": 30 + c / 100, "lat": 8 - r / 100} for c, r in [(0, 0), (900, 0), (0, 600), (900, 600)]]
    (run / "answer.c1.affine.json").write_text(json.dumps({"method": "affine", "gcps": gcps, "image": {"width": 955, "height": 669}}))
    P, inner = rg.panel_of(run, {"cand": 1, "method": "affine"})
    assert sorted(inner) == [[60, 533, 256, 619], [461, 14, 646, 268]]
