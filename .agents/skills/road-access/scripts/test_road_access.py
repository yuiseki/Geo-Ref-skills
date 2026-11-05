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
