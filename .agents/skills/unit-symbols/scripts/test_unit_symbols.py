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
    assert L.arm_of('d6', '') == 'infantry'
    assert L.arm_of('c12+h8v8', '') == 'transport'
    assert L.arm_of('c12+zzz', '') == 'artillery'  # the first part of a mixed signature
    assert L.arm_of('', 'UNMO') == 'military observers'
    assert L.arm_of('', 'unknown') is None
    assert L.arm_of(None, '') is None
