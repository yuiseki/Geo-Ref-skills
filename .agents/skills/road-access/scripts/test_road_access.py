# uvx --with pypdfium2 --with numpy --with pytest pytest scripts/test_road_access.py
import road_access as ra


def w(text, x, y, size=5.0):
    return {"text": text, "kind": "word", "x": x, "y": y, "w": 0.55 * size * len(text), "h": size, "size": size}


def row(no, road, truck, y, x0=440.0):
    out = [w(no, x0 + 4, y)]
    x = x0 + 14
    for t in road.split(" "):
        out.append(w(t, x + 0.55 * 5 * len(t) / 2, y))
        x += 0.55 * 5 * len(t) + 2
    out.append(w(truck, x0 + 75, y))
    return out


def test_status_follows_the_hue_of_the_legend_colours():
    assert ra.status_of((0, 176, 80)) == "passable"
    assert ra.status_of((76, 230, 0)) == "passable"
    assert ra.status_of((255, 255, 0)) == "passable with difficulties"
    assert ra.status_of((255, 192, 0)) == "passable with difficulties"  # orange, the 2025-2026 winter versions
    assert ra.status_of((255, 170, 0)) == "passable with difficulties"
    assert ra.status_of((255, 0, 0)) == "not passable"
    assert ra.status_of((255, 51, 0)) == "not passable"
    assert ra.status_of((230, 0, 0)) == "not passable"
    assert ra.status_of((63, 63, 63)) is None and ra.status_of((217, 217, 217)) is None


def test_table_rows_take_their_status_from_the_fill_under_the_road_cell():
    words = ([w("No.", 444, 2), w("Road", 470, 2), w("Truck", 515, 2), w("Type", 522, 2), w("Truck", 600, 2)]
             + row("U04", "Adar - Maban", "40MT", 10) + row("N02", "Aweil - Yith Pabol", "40MT", 17)
             + row("U08", "Adar - Mathiang", "", 24)
             # a second column of the table to the right
             + row("C03", "Juba - Kajo Keji", "20MT", 10, x0=525) + row("J07", "Pajut- Yuai", "", 17, x0=525)
             # map labels elsewhere: not in a column
             + [w("C09", 200, 100), w("Juba", 210, 110)])
    fills = [{"fill": (0, 176, 80), "box": (448, 6, 524, 20)}, {"fill": (255, 0, 0), "box": (448, 20, 524, 27)},
             {"fill": (255, 255, 0), "box": (533, 6, 610, 13)}, {"fill": (255, 0, 0), "box": (533, 13, 610, 20)},
             {"fill": (217, 217, 217), "box": (440, 6, 448, 27)}]
    rows = ra.table_rows(words, fills, min_rows=2)
    got = {r["id"]: (r["from"], r["to"], r["truck"], r["status"]) for r in rows}
    assert got == {"U04": ("Adar", "Maban", "40MT", "passable"), "N02": ("Aweil", "Yith Pabol", "40MT", "passable"),
                   "U08": ("Adar", "Mathiang", None, "not passable"),
                   "C03": ("Juba", "Kajo Keji", "20MT", "passable with difficulties"),
                   "J07": ("Pajut", "Yuai", None, "not passable")}


def test_numbered_rows_are_read_too():
    # the versions of December 2025 to March 2026 number the roads 1 to 140
    words = [w("Truck", 515, 2)] + row("1", "Juba - Nimule", "40MT", 10) + row("12", "Kapoeta - Narus", "20MT", 17)
    fills = [{"fill": (0, 176, 80), "box": (448, 6, 524, 20)}]
    rows = ra.table_rows(words, fills, min_rows=2)
    assert [(r["id"], r["from"], r["to"], r["status"]) for r in rows] == [
        ("1", "Juba", "Nimule", "passable"), ("12", "Kapoeta", "Narus", "passable")]


def test_ends_split_on_any_dash_and_the_middle_names_are_via():
    words = [w("Truck", 515, 2)] + row("112", "Aweil – Akun – Gogrial", "20MT", 10) + row("C01", "Lainya - Yei - Morobo", "20MT", 17)
    fills = [{"fill": (255, 192, 0), "box": (448, 6, 524, 20)}]
    rows = ra.table_rows(words, fills, min_rows=2)
    assert [(r["from"], r["via"], r["to"]) for r in rows] == [("Aweil", ["Akun"], "Gogrial"), ("Lainya", ["Yei"], "Morobo")]


def test_numbers_on_the_map_that_happen_to_line_up_are_not_a_table():
    # the January 2026 version: road number shields on the map, one above another, with symbol glyphs beside them
    words = ([w("Truck", 515, 2)] + row("1", "Juba - Nimule", "40MT", 10) + row("12", "Kapoeta - Narus", "20MT", 17)
             + [w("56", 200, 50), w("!", 210, 50), w("96", 200, 90), w("Thok", 212, 90), w("65", 200, 130), w("!", 208, 130)])
    fills = [{"fill": (0, 176, 80), "box": (448, 6, 524, 20)}, {"fill": (225, 225, 225), "box": (0, 0, 440, 300)}]
    rows = ra.table_rows(words, fills, min_rows=2)
    assert [r["id"] for r in rows] == ["1", "12"]


def test_a_fill_over_the_whole_table_does_not_hide_the_cells():
    # the 18 September 2026 version draws a blue box over the whole table after the cells
    words = [w("Truck", 515, 2)] + row("U04", "Adar - Maban", "40MT", 10) + row("U08", "Adar - Mathiang", "", 17)
    fills = [{"fill": (0, 176, 80), "box": (448, 6, 524, 13)}, {"fill": (255, 0, 0), "box": (448, 13, 524, 20)},
             {"fill": (0, 0, 208), "box": (440, 0, 610, 300)},
             # a piece of the map's grey background that reaches under the table (19 January 2026)
             {"fill": (225, 225, 225), "box": (430, 15, 500, 19)}]
    assert [r["status"] for r in ra.table_rows(words, fills, min_rows=2)] == ["passable", "not passable"]


def test_pink_is_last_mile_delivery_by_land_cruiser():
    # a fourth class in the versions of March to June 2026 ("Last-Mile Delivery Possible by Land cruiser")
    assert ra.status_of((255, 190, 232)) == "last-mile delivery by land cruiser"


def path(stroke, pts, width=0.48):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"fill": None, "stroke": stroke, "width": width, "box": (min(xs), min(ys), max(xs), max(ys)),
            "pts": [(2 if i == 0 else 0, x, y) for i, (x, y) in enumerate(pts)]}  # pdfium: 2 moveto, 0 lineto


def test_road_lines_are_the_brightest_status_colour_at_its_usual_width():
    ps = [path((76, 230, 0), [(0, 0), (10, 0), (20, 5)]), path((92, 137, 68), [(0, 0), (10, 0), (20, 5)], 1.12),  # casing
          path((76, 230, 0), [(0, 10), (10, 10), (20, 10)]),
          path((255, 0, 0), [(0, 20), (5, 20), (9, 20)]),
          path((255, 0, 0), [(300, 300), (310, 300)], 2.72),  # the legend's swatch
          path((63, 63, 63), [(0, 30), (10, 30), (20, 30)])]  # a boundary
    got = ra.road_lines(ps)
    assert sorted((r["status"], len(r["parts"][0])) for r in got) == [("not passable", 3), ("passable", 3), ("passable", 3)]
    assert all(r["colour"] != (92, 137, 68) for r in got)


def test_a_path_with_several_moves_has_several_parts():
    p = path((255, 255, 0), [(0, 0), (10, 0), (20, 0), (30, 0)])
    p["pts"][2] = (2, 20, 0)  # moveto: a second part
    (r,) = ra.road_lines([p, path((255, 255, 0), [(0, 9), (1, 9), (2, 9)])])[:1]
    assert [len(x) for x in r["parts"]] == [2, 2]


def test_labels_on_the_map_go_to_the_nearest_line_and_their_rows():
    lines = [{"status": "passable", "colour": (76, 230, 0), "parts": [[(0, 0), (100, 0)]]},
             {"status": "not passable", "colour": (255, 0, 0), "parts": [[(0, 50), (100, 50)]]}]
    words = [w("C09", 40, 2), w("U08", 60, 47), w("T01", 50, 25)]  # T01 is 25 from both: too far
    rows = [{"id": "C09", "road": "Juba - Nimule", "status": "passable"},
            {"id": "U08", "road": "Adar - Mathiang", "status": "passable with difficulties"}]
    got = ra.link(lines, words, rows, max_d=8)
    assert got[0]["ids"] == ["C09"] and got[0]["rows"][0]["road"] == "Juba - Nimule" and got[0]["agrees"] is True
    assert got[1]["ids"] == ["U08"] and got[1]["agrees"] is False  # the line is red, the table says yellow


def test_the_road_colour_is_the_one_drawn_most_not_a_brighter_one_drawn_little():
    # January 2026: roads not passable in (230, 0, 0); a few short pieces elsewhere in (255, 0, 0)
    roads = [path((230, 0, 0), [(0, i), (10, i), (20, i), (30, i)], 0.96) for i in range(5)]
    other = [path((255, 0, 0), [(0, 50), (1, 50), (2, 50)], 0.96)]
    got = ra.road_lines(roads + other)
    assert len(got) == 5 and all(r["colour"] == (230, 0, 0) for r in got)


def test_stroked_rectangles_of_a_size_are_found_as_boxes():
    # the insets of May 2026 (about 60 pt a side) are under the 12% of the page that map_candidates takes as frames;
    # the boxes that mark what an inset enlarges (about 20 pt) and other shapes are not insets
    inset = path((0, 0, 208), [(160, 6), (237, 6), (237, 72), (160, 72), (160, 6)])
    marker = path((0, 0, 208), [(220, 105), (245, 105), (245, 120), (220, 120), (220, 105)])
    abyei = path((0, 0, 0), [(160, 80), (200, 80), (210, 100), (190, 120), (165, 110), (160, 80)])
    road = path((255, 255, 0), [(0, 0), (100, 0), (100, 100), (0, 100)])  # open: not a rectangle
    road["pts"] = road["pts"][:4]
    # May 2026: a frame begun and ended in the middle of its left side
    mid = path((0, 77, 168), [(246, 42), (246, 10), (303, 10), (303, 74), (246, 74), (246, 42)])
    # an inset hides the map under a white box; a box marking what an inset enlarges (June 2026: 40 by 61 pt
    # around Koch and Rupkuai) has none, and the roads in it are the map's
    def white(b):
        return {"fill": (255, 255, 255), "stroke": None, "width": 1.0, "box": b, "pts": [], "closed": True}
    locator = path((0, 77, 168), [(290, 136), (330, 136), (330, 197), (290, 197), (290, 136)])
    got = ra.rectangles([inset, white((160, 6, 237, 72)), marker, abyei, road, mid, white((246, 10, 303, 74)), locator],
                        min_side=40)
    assert got == [(160, 6, 237, 72), (246, 10, 303, 74)]
