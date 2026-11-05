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
