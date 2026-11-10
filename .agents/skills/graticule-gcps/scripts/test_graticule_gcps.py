# uvx --with pypdfium2 --with numpy --with pyproj --with pytest pytest scripts/test_graticule_gcps.py
import math

import graticule_gcps as G


def test_a_label_is_a_value_in_degrees_and_minutes_with_its_hemisphere():
    assert G.parse("36°20'E") == ("lon", 36 + 20 / 60)
    assert G.parse("36°E") == ("lon", 36.0)
    assert G.parse("32°45'N") == ("lat", 32.75)
    assert G.parse("8°35'S") == ("lat", -(8 + 35 / 60))
    assert G.parse("171°10'W") == ("lon", -(171 + 10 / 60))
    assert G.parse("12°30'15\"E") == ("lon", 12.5 + 15 / 3600)
    assert G.parse("Line") is None and G.parse("1072m") is None


def ch(c, l, t, r, b):
    return {"ch": c, "l": l, "t": t, "r": r, "b": b}


def test_labels_are_runs_of_the_text_layer_written_across_or_down():
    # UNDOF, September 2025: the labels of the left and right edges are written down the page, one character under
    # another; the text layer gives them in order, between line breaks
    across = [ch(c, 417.9 + 3 * i, 69.7, 420.7 + 3 * i, 74.1) for i, c in enumerate("36°10'E")]
    down = [ch(c, 24.9, 659.2 - 3 * i, 29.2, 661.9 - 3 * i) for i, c in enumerate("32°50'N")]
    cs = across + [ch("\n", 0, 0, 0, 0)] + down + [ch(" ", 0, 0, 0, 0)] + [ch(c, 300 + i, 300, 301 + i, 304) for i, c in enumerate("Hadar")]
    got = G.labels(cs)
    assert [(g["axis"], round(g["value"], 4)) for g in got] == [("lon", round(36 + 10 / 60, 4)), ("lat", round(32 + 50 / 60, 4))]
    assert got[0]["box"] == (417.9, 69.7, 438.7, 74.1)
    assert not got[0]["down"] and got[1]["down"]


def tick(x0, y0, x1, y1):
    return ((x0, y0), (x1, y1))


def test_a_label_takes_the_short_tick_beside_it_on_its_line():
    lon = {"axis": "lon", "value": 36.0, "box": (417.9, 69.7, 438.0, 74.1), "down": False}
    lat = {"axis": "lat", "value": 32.8, "box": (24.9, 641.7, 29.2, 661.9), "down": True}
    ticks = [tick(427.99, 75.96, 427.99, 78.26), tick(445.0, 76.0, 445.0, 78.3),   # its tick and the next one's
             tick(31.2, 651.64, 33.5, 651.64), tick(31.2, 600.0, 33.5, 600.0)]
    assert G.tick_of(lon, ticks) == (427.99, 77.11)
    assert G.tick_of(lat, ticks) == (32.35, 651.64)
    assert G.tick_of({**lon, "box": (100.0, 69.7, 120.0, 74.1)}, ticks) is None


def test_meridians_join_the_ticks_of_one_value_and_a_lone_tick_takes_their_direction():
    # 36°10'E is at x 428 at the top and 434 at the bottom (the map's north is not true north); 35°45'E is hidden at
    # the top by the globe, and runs parallel to the others from its bottom tick
    marks = [("lon", 36 + 10 / 60, (428.0, 77.0)), ("lon", 36 + 10 / 60, (434.0, 752.0)),
             ("lon", 36.0, (300.0, 77.0)), ("lon", 36.0, (306.0, 752.0)),
             ("lon", 35.75, (110.0, 752.0)), ("lat", 33.0, (32.0, 400.0))]
    lines = G.lines(marks)
    lon = {v: (p, d) for a, v, p, d in lines if a == "lon"}
    assert set(lon) == {36 + 10 / 60, 36.0, 35.75}
    p, d = lon[35.75]
    assert p == (110.0, 752.0) and math.isclose(d[0] / d[1], 6.0 / 675.0, rel_tol=1e-9)
    assert not any(a == "lat" for a, *_ in lines)  # one lat tick and no direction to give it


def test_control_points_are_where_meridians_cross_parallels():
    lines = [("lon", 36.0, (300.0, 0.0), (0.0, 1.0)), ("lon", 36.5, (400.0, 0.0), (0.0, 1.0)),
             ("lat", 33.0, (0.0, 200.0), (1.0, 0.0)), ("lat", 32.5, (0.0, 300.0), (1.0, 0.0))]
    got = G.crossings(lines)
    assert sorted((round(x, 6), round(y, 6), lon, lat) for x, y, lon, lat in got) == [
        (300.0, 200.0, 36.0, 33.0), (300.0, 300.0, 36.0, 32.5), (400.0, 200.0, 36.5, 33.0), (400.0, 300.0, 36.5, 32.5)]


def test_points_become_pixels_of_the_crop_and_those_outside_it_are_left_out():
    pts = [(300.0, 200.0, 36.0, 33.0), (10.0, 10.0, 35.0, 34.0)]
    got = G.to_pixels(pts, dpi=144.0, box_px=(100, 100, 900, 900))
    assert got == [{"col": 500.0, "row": 300.0, "lon": 36.0, "lat": 33.0, "name": "36°0'E 33°0'N"}]


def test_a_grid_label_is_metres_east_or_north():
    # UNIFIL, 2025: a UTM grid, labelled 700000E and 3700000N (the last three zeros smaller)
    assert G.parse("700000E") == ("x", 700000.0)
    assert G.parse("3700000N") == ("y", 3700000.0)
    assert G.parse("1072m") is None and G.parse("2014") is None and G.parse("12E") is None


def test_a_grid_label_takes_the_long_line_through_its_middle():
    lab = {"axis": "x", "value": 700000.0, "box": (81.1, 40.0, 104.3, 46.2), "down": False}
    lines = [((92.8, 35.3), (92.8, 562.6)), ((300.0, 35.3), (300.0, 562.6)), ((40.0, 100.0), (750.0, 100.0))]
    got = G.grid_line_of(lab, lines)
    assert got == ((92.8, 35.3), (0.0, 1.0))
    lab_y = {"axis": "y", "value": 3700000.0, "box": (44.7, 74.9, 67.6, 81.0), "down": False}
    assert G.grid_line_of(lab_y, lines) is None  # no horizontal line through it within 1.5 pt
    assert G.grid_line_of({**lab_y, "box": (44.7, 97.0, 67.6, 103.0)}, lines) == ((40.0, 100.0), (1.0, 0.0))


def test_grid_crossings_are_turned_into_degrees_by_the_utm_zone():
    lines = [("x", 700000.0, (92.8, 0.0), (0.0, 1.0)), ("y", 3700000.0, (0.0, 78.0), (1.0, 0.0))]
    (x, y, lon, lat), = G.crossings(lines, zone="36N")
    assert (round(x, 6), round(y, 6)) == (92.8, 78.0)
    assert math.isclose(lon, 35.15103, abs_tol=1e-5) and math.isclose(lat, 33.42074, abs_tol=1e-5)


def test_a_grid_without_a_zone_gives_no_points():
    lines = [("x", 700000.0, (92.8, 0.0), (0.0, 1.0)), ("y", 3700000.0, (0.0, 78.0), (1.0, 0.0))]
    assert G.crossings(lines) == []


def test_a_path_is_straight_when_every_point_lies_on_its_ends_line():
    # UNIFIL's grid lines are paths of 12 to 15 points along one line
    assert G.straight([(92.8, 35.3), (92.8, 77.4), (92.81, 130.7), (92.8, 562.6)]) == ((92.8, 35.3), (92.8, 562.6))
    assert G.straight([(0.0, 0.0), (5.0, 3.0), (10.0, 0.0)]) is None
    assert G.straight([(1.0, 1.0)]) is None


def test_a_graticule_over_more_than_a_few_degrees_is_not_taken_as_straight():
    # MINUSMA, 2024: ticks every degree over 15 x 15 degrees of Mali passed every gate with 12 crossings, and put
    # Bamako 20 km and Gao 9 km off: meridians and parallels curve over that span. UNDOF spans 0.7 degrees.
    small = [(0, 0, 35.7, 32.8), (0, 0, 36.3, 33.4)]
    wide = [(0, 0, -15.0, 10.0), (0, 0, -5.0, 25.0)]
    assert G.too_wide(wide) and not G.too_wide(small)
