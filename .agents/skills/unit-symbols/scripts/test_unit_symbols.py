# uvx --with pypdfium2 --with numpy --with pytest pytest scripts/test_unit_symbols.py
import unit_symbols as L

BLUE = (29, 118, 182)


def line(x0, y0, x1, y1):
    return {'fill': None, 'stroke': BLUE, 'box': (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
            'segs': [(2, x0, y0), (0, x1, y1)]}


def test_marks_are_bars_dots_and_crosses():
    assert L.mark_kind(line(105, 188.4, 105, 193.2)) == 'bar'
    x = {'fill': None, 'stroke': BLUE, 'box': (104.1, 169.1, 109.8, 174.8),
         'segs': [(2, 104.5, 169.5), (0, 109.5, 174.5), (2, 109.5, 169.5), (0, 104.5, 174.5)]}
    assert L.mark_kind(x) == 'x'
    dot = {'fill': BLUE, 'stroke': None, 'box': (100, 100, 3, 3), 'segs': [(2, 101.5, 100), (1, 103, 101.5), (1, 101.5, 103),
                                                                           (1, 100, 101.5), (1, 101.5, 100)]}
    dot['box'] = (100, 100, 103, 103)
    assert L.mark_kind(dot) == 'dot'
    assert L.mark_kind({**dot, 'fill': None, 'stroke': BLUE}) == 'ring'


def test_echelon_follows_the_size_indicator_table():
    # UN Military Symbols Handbook (2000), p. 26
    assert L.echelon(['bar']) == 'company'
    assert L.echelon(['bar', 'bar']) == 'battalion'
    assert L.echelon(['bar'] * 3) == 'regiment'
    assert L.echelon(['dot'] * 3) == 'platoon'
    assert L.echelon(['dot']) == 'squad'
    assert L.echelon(['ring']) == 'team'
    assert L.echelon(['x']) == 'brigade'
    assert L.echelon(['x', 'x']) == 'division'
    assert L.echelon([]) is None
    assert L.echelon(['bar', 'dot']) is None  # mixed: not a size indicator


def test_marks_touching_the_frame_top_are_found():
    frame = (96.7, 191.9, 117.2, 204.1)
    ps = [line(105.0, 188.4, 105.0, 193.2), line(108.6, 188.4, 108.6, 193.2), line(90, 150, 90, 160)]
    assert [L.mark_kind(p) for p in L.marks_above(frame, ps)] == ['bar', 'bar']


def test_the_arm_comes_from_the_drawn_symbol_then_from_the_abbreviation_inside():
    assert L.arm_of('d5', '') == 'infantry'
    assert L.arm_of('c12h2+d5', '') == 'mechanized infantry'
    assert L.arm_of('c12+h8v8', '') == 'transport'
    assert L.arm_of('', 'UNMO') == 'military observers'
    assert L.arm_of('', 'unknown') is None
    assert L.arm_of(None, '') is None


def test_a_staff_or_a_headquarters_bar_beside_the_symbol_does_not_hide_it():
    # the leader's staff (v1) and the headquarters bar (h1) are paths of their own inside the frame's box
    assert L.arm_of('d5+v1', '') == L.arm_of('d5+h1', '') == 'infantry'
    assert L.arm_of('h2v2+v1', '') == L.arm_of('h2v2+v1+v1', '') == 'medical'
    assert L.arm_of('h1', 'SHQ') == 'sector headquarters'


def test_an_anchor_is_riverine_not_the_circle_it_starts_with():
    assert L.arm_of('c12+c6+h1+v1', '') == 'riverine'
    assert L.arm_of('c12+zzz', '') is None  # no guessing from the first part

def poly(b, pts):
    """A path through points given as fractions of the frame box b."""
    w, h = b[2] - b[0], b[3] - b[1]
    return [(2 if i == 0 else 0, b[0] + x * w, b[1] + y * h) for i, (x, y) in enumerate(pts)]


def test_a_symbol_drawn_with_extra_points_on_its_lines_has_the_same_signature():
    # the 2023-2025 UNMISS maps put a point halfway along each line of the engineer and medical symbols; the 2020
    # maps do not. Same picture, two signatures, and the older maps' arms were lost (2026-11-05)
    b = (0, 0, 20, 12)
    old = poly(b, [(0.23, 0.71), (0.23, 0.31), (0.49, 0.31), (0.49, 0.71), (0.49, 0.31), (0.76, 0.31), (0.76, 0.71)])
    new = poly(b, [(0.23, 0.71), (0.23, 0.31), (0.49, 0.31), (0.49, 0.51), (0.49, 0.71), (0.49, 0.31), (0.76, 0.31), (0.76, 0.71)])
    assert L.signature({'box': b, 'segs': old}) == L.signature({'box': b, 'segs': new})
    cross_old = poly(b, [(0.14, 0.5), (0.86, 0.5), (0.5, 0.5), (0.5, 0.19), (0.5, 0.8)])
    cross_new = poly(b, [(0.14, 0.5), (0.5, 0.5), (0.86, 0.5), (0.5, 0.5), (0.5, 0.2), (0.5, 0.5), (0.5, 0.81)])
    assert L.signature({'box': b, 'segs': cross_old}) == L.signature({'box': b, 'segs': cross_new})
    bolt_old = poly(b, [(0.03, 0.06), (0.49, 0.68), (0.49, 0.39), (0.97, 0.94)])
    bolt_new = poly(b, [(0.03, 0.06), (0.49, 0.68), (0.49, 0.53), (0.49, 0.39), (0.97, 0.94)])
    assert L.signature({'box': b, 'segs': bolt_old}) == L.signature({'box': b, 'segs': bolt_new})


def test_paths_inside_a_form_are_read_where_the_page_draws_them(tmp_path):
    # the town dots of MONUSCO's map of June 2025 are in a form XObject; read only at the top level, no leader
    # found the place it ends at, and 61 of 68 units had no position or a wrong one
    import pypdfium2 as pdfium
    from test_pdf_words import pdf_with_form

    pdf = pdf_with_form(tmp_path / "f.pdf", (2, 0, 0, 2, 10, 10), (1, 0, 0, 1, 50, 20),
                        inner=b"0.15 0.46 0.71 rg 0 0 2 2 re f")
    ps = L.paths_of(pdfium.PdfDocument(str(pdf))[0])
    dot = [p for p in ps if L.is_blue(p["fill"])]
    assert len(dot) == 1
    # page space: x from 2 * 50 + 10 = 110 to 114, y from 2 * 20 + 10 = 50 to 54, shown from the top (200 - y)
    assert [round(v, 3) for v in dot[0]["box"]] == [110, 146, 114, 150]
    assert {(round(x, 3), round(y, 3)) for _, x, y in dot[0]["segs"]} >= {(110, 150), (114, 146)}


def lead(*pts):
    return {"segs": [(2 if i == 0 else 0, x, y) for i, (x, y) in enumerate(pts)]}


def test_a_leader_ending_on_another_line_reaches_the_place_at_that_lines_end():
    # MONUSCO, June 2025: the Force stack's leader ends on a short line hanging from Goma's symbol, 13 pt below it
    goma = {"x": 606.0, "y": 470.4, "kind": "circle"}
    other = {"x": 560.0, "y": 483.0, "kind": "dot"}
    stack = (694.0, 353.0, 711.0, 526.0)
    leaders = [lead((605.4, 483.1), (692.9, 483.0), (693.2, 541.7), (694.5, 541.7), (694.5, 353.6)),
               lead((605.7, 473.3), (605.6, 483.2))]
    loc, how, _ = L.locate(stack, leaders, [goma, other])
    assert (loc, how) == (goma, "leader")


def test_of_two_leaders_near_a_stack_the_one_starting_on_it_wins():
    # two Morocco stacks one above the other: the lower one's leader starts 5 pt under the upper one
    kiwanja, kitchanga = {"x": 611.7, "y": 422.3, "kind": "dot"}, {"x": 581.8, "y": 437.6, "kind": "dot"}
    upper = (622.0, 326.0, 640.0, 377.0)
    leaders = [lead((612.1, 422.3), (622.5, 422.2), (622.5, 326.7)),
               lead((581.8, 437.3), (630.5, 437.4), (630.6, 382.3))]
    loc, how, _ = L.locate(upper, leaders, [kiwanja, kitchanga])
    assert (loc, how) == (kiwanja, "leader")


def test_two_leaders_starting_on_a_stack_to_two_places_are_ambiguous():
    a, b = {"x": 0.0, "y": 0.0, "kind": "dot"}, {"x": 0.0, "y": 100.0, "kind": "dot"}
    leaders = [lead((0, 0), (50, 10)), lead((0, 100), (50, 20))]
    loc, how, cands = L.locate((50.0, 5.0, 70.0, 30.0), leaders, [a, b])
    assert (loc, how) == (None, "ambiguous") and len(cands) == 2


def test_unit_frames_come_from_the_top_level_when_it_has_any():
    # MONUSCO, June 2025: 88 frames at the top level, 3 shapes of a frame's size in the base map's form XObject;
    # other maps of 2017 to 2025 have their frames at one level only (some with no label: not a sign of a shape)
    blue = (39, 118, 181)

    def fr(x, level):
        return {"stroke": blue, "fill": None, "box": (x, 100.0, x + 18.0, 110.0), "segs": [], "level": level}
    top, deep = [fr(100.0, 0), fr(200.0, 0)], [fr(300.0, 1)]
    assert L.unit_frames(top + deep) == top
    assert L.unit_frames(deep) == deep


def test_a_line_drawn_along_a_frame_is_not_a_leader():
    # the headquarters bar of a Morocco frame (MONUSCO, June 2025) is a separate line on the frame's top edge; its
    # end lies on the frame's own leader, and the FIB stack beside it was led through it to Kiwanja
    blue = (39, 118, 181)
    frame = {"stroke": blue, "fill": None, "box": (622.2, 326.1, 639.3, 336.0),
             "segs": [(2, 622.6, 326.5), (0, 638.9, 326.5), (0, 638.9, 335.6), (0, 622.6, 335.6), (0, 622.6, 326.5)]}
    bar = {"stroke": blue, "fill": None, "box": (622.2, 326.1, 639.3, 326.9),
           "segs": [(2, 638.9, 326.5), (0, 632.3, 326.5), (0, 622.6, 326.5)]}
    leader = {"stroke": blue, "fill": None, "box": (611.7, 326.3, 622.9, 422.7),
              "segs": [(2, 612.1, 422.3), (0, 622.5, 422.2), (0, 622.5, 326.7)]}
    got = L.leader_lines([frame, bar, leader], [frame])
    assert got == [leader]


def test_a_stack_whose_own_line_joins_a_neighbours_leader_goes_where_that_leader_goes():
    # MONUSCO, June 2025: the FIB column's line runs down its left edge and ends on the leader of the South Africa
    # QRF column, which goes to Beni; both ends of the FIB line are within the column
    beni = {"x": 577.8, "y": 274.0, "kind": "dot"}
    fib = (639.7, 229.2, 657.6, 317.6)
    leaders = [lead((640.1, 320.5), (640.8, 230.4)),
               lead((577.8, 273.4), (577.8, 266.2), (636.2, 266.6), (636.1, 320.6), (688.6, 320.6), (689.0, 268.3))]
    loc, how, _ = L.locate(fib, leaders, [beni])
    assert (loc, how) == (beni, "leader")


def test_blocks_of_a_column_led_to_two_places_are_two_stacks():
    # an INDIA block over an INDIA / SENEGAL block, 15 pt apart, each with its own leader (MONUSCO, June 2025)
    sake, himbi = {"x": 572.7, "y": 435.4, "kind": "dot"}, {"x": 600.0, "y": 469.8, "kind": "dot"}
    upper = [{"box": [508.0, 378.0, 526.0, 388.0]}, {"box": [508.0, 390.0, 526.0, 425.0]}]
    lower = [{"box": [508.0, 440.0, 526.0, 450.0]}, {"box": [508.0, 455.0, 526.0, 465.0]}]
    leaders = [lead((572.7, 435.4), (508.4, 435.3), (508.4, 383.7)),
               lead((600.0, 469.8), (509.5, 470.4), (509.4, 448.7))]
    got = L.locate_column([upper, lower], leaders, [sake, himbi])
    assert [(len(st), loc, how) for st, loc, how, _ in got] == [(2, sake, "leader"), (2, himbi, "leader")]


def test_a_column_with_one_leader_stays_one_stack():
    town = {"x": 400.0, "y": 300.0, "kind": "dot"}
    upper = [{"box": [508.0, 378.0, 526.0, 388.0]}]
    lower = [{"box": [508.0, 410.0, 526.0, 420.0]}]
    got = L.locate_column([upper, lower], [lead((400.0, 300.0), (508.4, 380.0))], [town])
    assert [(len(st), loc, how) for st, loc, how, _ in got] == [(2, town, "leader")]


def test_a_dot_drawn_inside_a_frame_is_a_symbol_not_a_place():
    frames = [{"box": (100.0, 100.0, 118.0, 110.0)}]
    places = [{"x": 109.0, "y": 105.0}, {"x": 140.0, "y": 105.0}]
    assert L.outside_frames(places, frames) == [{"x": 140.0, "y": 105.0}]
