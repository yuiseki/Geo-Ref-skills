"""Units on a peacekeeping deployment map PDF (vector, blue unit frames), as points in page coordinates (level 6).

    python scripts/unit_symbols.py map.pdf --out units.json [--debug overlay.png]

The map is read from the PDF's drawing and text layers, with no model: blue unit frames (12 to 30 pt wide), the
label to the right, the abbreviation or symbol inside, size marks above (UN Military Symbols Handbook, DPKO 2000,
p.26: ring, dots, bars, crosses), frames stacked in a column, and the leader line whose end is the unit's exact
position (p.28). A stack with no leader takes the place symbol beside it. Places are blue dots, symbol-font markers
and small circles. Positions are page points, origin top left, as the page is shown (after /Rotate).
"""
import argparse, json, ctypes, math, collections
import pypdfium2 as pdfium, pypdfium2.raw as R
import pdf_words as pw

# what is drawn inside a unit frame -> arm, by NATO APP-6 (the handbook gives the size indicators and the staff but
# no table of arms); checked by eye on a contact sheet of one frame per signature over 80 maps of 2017 to 2025
# (2026-11-05), the signatures counting a straight run of segments as one line (straight_runs)
ARM = {'d5': 'infantry', 'c12h2+d5': 'mechanized infantry', 'h2v4': 'engineer', 'h2v2': 'medical', 'd2v1': 'signal',
       'h4v5': 'aviation (rotary wing)', 'h4v7': 'aviation (rotary wing)', 'h2+h4v5': 'aviation (rotary wing)',
       'c18h3': 'aviation (fixed wing)', 'c12h2': 'armour', 'd1': 'reconnaissance', 'c12h2+d2': 'armoured reconnaissance',
       'c12h2+d3': 'armoured reconnaissance', 'c6+c6+h1': 'maintenance', 'c12+h8v8': 'transport', 'c12+h10v6': 'transport',
       # an anchor: a ring, a shank with a stock, arms with flukes
       'c12+c6+h1+v1': 'riverine', 'c12+c6+h1+h2v2+h2v2+v1': 'riverine',
       'c12+c12+c12+c6+c6+h1+h2v1+h2v1+v1': 'riverine', 'c12+c12+c12+c6+c6+h1+h1v2+h2v1+v1': 'riverine'}
# abbreviations written inside a frame instead (UN usage)
INNER = {'HQ': 'headquarters', 'SHQ': 'sector headquarters', 'FHQ': 'force headquarters', 'UNMO': 'military observers',
         'FPU': 'formed police unit', 'IPO': 'individual police officers', 'MP': 'military police',
         'QRF': 'quick reaction force', 'SF': 'special forces', 'SOF': 'special operations forces',
         'EOD': 'explosive ordnance disposal', 'MLT': 'military liaison team', 'PSU': 'protection support unit'}


def arm_of(signature, inner):
    """The arm of a unit: its symbol's signature, else that signature without the single lines that are paths of
    their own (the leader's staff v1, the headquarters bar h1), else the abbreviation written inside."""
    sig = signature or ''
    core = '+'.join(p for p in sig.split('+') if p not in ('v1', 'h1'))
    return ARM.get(sig) or ARM.get(core) or INNER.get(inner)


def col(fn, o):
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    return (r.value, g.value, b.value) if fn(o, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)) else None


def is_blue(c):
    return c is not None and c[2] > 140 and c[0] < 90 and 80 < c[1] < 170


def paths_of(page):
    # paths are in the unturned page's space; the page may be shown turned by /Rotate (2021-2022 maps)
    rot = page.get_rotation()
    W0, H0 = page.get_size()
    if rot % 180:
        W0, H0 = H0, W0
    out = []
    for o in page.get_objects(max_depth=0):
        if o.type != 2:
            continue
        raw = o.raw
        mode, st = ctypes.c_int(), ctypes.c_int()
        R.FPDFPath_GetDrawMode(raw, ctypes.byref(mode), ctypes.byref(st))
        m = o.get_matrix()
        segs = []
        for i in range(R.FPDFPath_CountSegments(raw)):
            s = R.FPDFPath_GetPathSegment(raw, i)
            x, y = ctypes.c_float(), ctypes.c_float()
            R.FPDFPathSegment_GetPoint(s, ctypes.byref(x), ctypes.byref(y))
            X, Y = m.a * x.value + m.c * y.value + m.e, m.b * x.value + m.d * y.value + m.f
            segs.append((R.FPDFPathSegment_GetType(s), *pw.display(X, Y, rot, W0, H0)))
        l, b, r, t = o.get_bounds()
        out.append({'fill': col(R.FPDFPageObj_GetFillColor, raw) if mode.value else None,
                    'stroke': col(R.FPDFPageObj_GetStrokeColor, raw) if st.value else None,
                    'box': pw.display_box(l, b, r, t, rot, W0, H0), 'segs': segs})
    return out


def wh(b):
    return b[2] - b[0], b[3] - b[1]


def inside(pt, b, pad=0.0):
    return b[0] - pad <= pt[0] <= b[2] + pad and b[1] - pad <= pt[1] <= b[3] + pad


def straight_runs(segs):
    """The straight lines of a path, a run of segments going on in one direction joined into one: a symbol drawn
    with a point halfway along a line (UNMISS 2023-2025) gives the lines of one drawn without it (2020). Curves
    count one each, as 'c'."""
    out, last = [], None
    for (t0, x0, y0), (t1, x1, y1) in zip(segs, segs[1:]):
        if t1 == 1:
            out.append(('c',))
            last = None
            continue
        if t1 != 0:
            last = None
            continue
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy)
        if n < 1e-9:
            continue
        if last is not None and out and out[-1][0] == 'l':
            _, ax, ay, bx, by = out[-1]
            px, py = bx - ax, by - ay
            m = math.hypot(px, py)
            # the same direction, not a turn back along the line (that is a second stroke: the cross's arms)
            if (bx, by) == (x0, y0) and (px * dx + py * dy) / (m * n) > 0.999:
                out[-1] = ('l', ax, ay, x1, y1)
                continue
        out.append(('l', x0, y0, x1, y1))
        last = (x1, y1)
    return out


def signature(frame):
    """What is drawn inside the frame, beyond the rectangle: lines by direction (d diagonal, h, v), curves."""
    b = frame['box']
    w, h = wh(b)
    kinds = collections.Counter()
    for r in straight_runs(frame['segs']):
        if r[0] == 'c':
            kinds['c'] += 1
            continue
        _, x0, y0, x1, y1 = r
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        on_edge = (dx < 0.5 and (abs(x0 - b[0]) < 1 or abs(x0 - b[2]) < 1)) or (dy < 0.5 and (abs(y0 - b[1]) < 1 or abs(y0 - b[3]) < 1))
        if on_edge:
            continue
        kinds['d' if dx > 0.3 * w and dy > 0.3 * h else ('h' if dx >= dy else 'v')] += 1
    return ''.join(f'{k}{v}' for k, v in sorted(kinds.items()))


def mark_kind(p):
    """A size indicator piece: 'bar' (a short vertical line), 'x' (crossing diagonals), 'dot' (a filled round),
    'ring' (a hollow round), else None."""
    w, h = wh(p['box'])
    segs = p['segs']
    if any(t == 1 for t, _, _ in segs) and 0.6 <= (w + 1e-6) / (h + 1e-6) <= 1.6:
        return 'dot' if is_blue(p['fill']) else ('ring' if is_blue(p['stroke']) else None)
    diag = sum(1 for (_, x0, y0), (t1, x1, y1) in zip(segs, segs[1:]) if t1 == 0
               and abs(x1 - x0) > 0.3 * w and abs(y1 - y0) > 0.3 * h and w > 1 and h > 1)
    if diag >= 2 and 0.6 <= w / h <= 1.6:
        return 'x'
    if h >= 2 and w <= 0.6 * h:
        return 'bar'
    return None


# UN Military Symbols Handbook (2000), p. 26: the size indicator over a unit symbol
ECHELON = {('ring', 1): 'team', ('dot', 1): 'squad', ('dot', 2): 'section', ('dot', 3): 'platoon',
           ('bar', 1): 'company', ('bar', 2): 'battalion', ('bar', 3): 'regiment', ('x', 1): 'brigade',
           ('x', 2): 'division', ('x', 3): 'corps', ('x', 4): 'army', ('x', 5): 'army group'}


def echelon(kinds):
    if not kinds or len(set(kinds)) != 1:
        return None
    return ECHELON.get((kinds[0], len(kinds)))


def marks_above(b, ps, band=8.0):
    """The pieces of a size indicator: small blue paths over the frame's top edge, centred within its width. Their
    strokes reach into the frame by about a point (UNMISS, 2026-11-04), so they may overlap it a little."""
    out = []
    for p in ps:
        w, h = wh(p['box'])
        if not is_blue(p['stroke'] or p['fill']) or w >= 8 or h >= 8:
            continue
        if b[0] <= (p['box'][0] + p['box'][2]) / 2 <= b[2] and -2.0 <= b[1] - p['box'][3] <= band - h \
                and p['box'][1] < b[1] and mark_kind(p):
            out.append(p)
    return sorted(out, key=lambda p: p['box'][0])


def main(pdf, out, debug=None):
    doc = pdfium.PdfDocument(pdf)
    page = doc[0]
    W, H = page.get_size()
    ps = paths_of(page)
    words = [w for w in pw.words(pw.chars(pdf)) if w['kind'] == 'word']
    blue_words = [w for w in words if is_blue(w.get('colour'))]
    frames = [p for p in ps if is_blue(p['stroke']) and 12 <= wh(p['box'])[0] <= 30 and 7 <= wh(p['box'])[1] <= 16
              and 1.3 <= wh(p['box'])[0] / wh(p['box'])[1] <= 2.4]
    # one frame per place: outline and inner symbol may be separate paths
    uniq = []
    for f in sorted(frames, key=lambda f: -wh(f['box'])[0] * wh(f['box'])[1]):
        if all(abs(f['box'][0] - g['box'][0]) > 3 or abs(f['box'][1] - g['box'][1]) > 3 for g in uniq):
            uniq.append(f)
    frames = uniq
    blue_paths = [p for p in ps if is_blue(p['stroke'])]
    units = []
    for f in frames:
        b = f['box']
        cy = (b[1] + b[3]) / 2
        inner = [w['text'] for w in blue_words if inside((w['x'], w['y']), b)]
        right = sorted([w for w in blue_words if 0 <= w['x'] - w['w'] / 2 - b[2] <= 60 and abs(w['y'] - cy) < 0.5 * (b[3] - b[1])],
                       key=lambda w: w['x'])
        label, last = [], b[2]
        for w in right:
            if w['x'] - w['w'] / 2 - last > 8:
                break
            label.append(w['text'])
            last = w['x'] + w['w'] / 2
        above = [mark_kind(p) for p in marks_above(b, ps) if p is not f]
        units.append({'box': [round(v, 2) for v in b], 'inner': ' '.join(inner), 'label': ' '.join(label),
                      'signature': '+'.join(sorted(x for x in (signature({'box': b, 'segs': q['segs']}) for q in blue_paths
                                                                  if inside(((q['box'][0] + q['box'][2]) / 2, (q['box'][1] + q['box'][3]) / 2), b, 0.5)
                                                                  and max(wh(q['box'])) <= max(wh(b)) + 1) if x)),
                      'marks_above': len(above), 'size_marks': above, 'echelon': echelon(above)})
        units[-1]['arm'] = arm_of(units[-1]['signature'], units[-1]['inner'])
    # stacks: frames with the same left edge, one under another
    units.sort(key=lambda u: (round(u['box'][0]), u['box'][1]))
    stacks = []
    for u in units:
        for s in stacks:
            v = s[-1]
            if abs(u['box'][0] - v['box'][0]) < 2 and 0 <= u['box'][1] - v['box'][3] <= 14:
                s.append(u)
                break
        else:
            stacks.append([u])
    dots = [p for p in ps if is_blue(p['fill']) and max(wh(p['box'])) < 6]
    marks = [{'x': m['x'], 'y': m['y']} for m in pw.markers(pw.chars(pdf))]
    # towns drawn as small circles (curves, a few points across, any colour), besides blue dots and symbol-font marks
    circles = [p for p in ps if any(t == 1 for t, _, _ in p['segs']) and 1.5 <= max(wh(p['box'])) <= 7
               and 0.7 <= (wh(p['box'])[0] + 1e-6) / (wh(p['box'])[1] + 1e-6) <= 1.4 and not is_blue(p['fill'])]
    places = [{'x': (d['box'][0] + d['box'][2]) / 2, 'y': (d['box'][1] + d['box'][3]) / 2, 'kind': 'dot'} for d in dots] + \
             [{**m, 'kind': 'marker'} for m in marks] + \
             [{'x': (d['box'][0] + d['box'][2]) / 2, 'y': (d['box'][1] + d['box'][3]) / 2, 'kind': 'circle'} for d in circles]
    # stacks one under another in one column are one stack (a column is drawn with gaps between its blocks)
    merged = True
    while merged:
        merged = False
        for a in range(len(stacks)):
            for b in range(len(stacks)):
                if a == b:
                    continue
                A, B = stacks[a], stacks[b]
                if abs(A[0]['box'][0] - B[0]['box'][0]) < 2 and 0 <= B[0]['box'][1] - A[-1]['box'][3] <= 30:
                    stacks[a] = A + B
                    del stacks[b]
                    merged = True
                    break
            if merged:
                break
    leaders = [p for p in ps if is_blue(p['stroke']) and 2 <= len(p['segs']) <= 8 and max(wh(p['box'])) > 6
               and not any(p is f for f in frames)]
    res = []
    for k, st in enumerate(stacks):
        sb = (min(u['box'][0] for u in st), min(u['box'][1] for u in st), max(u['box'][2] for u in st), max(u['box'][3] for u in st))
        found = []
        for L in leaders:
            ends = [(L['segs'][0][1], L['segs'][0][2]), (L['segs'][-1][1], L['segs'][-1][2])]
            for e, other in ((ends[0], ends[1]), (ends[1], ends[0])):
                if inside(e, sb, pad=12) and not inside(other, sb, pad=12):
                    near = min(places, key=lambda q: math.hypot(q['x'] - other[0], q['y'] - other[1]), default=None)
                    if near and math.hypot(near['x'] - other[0], near['y'] - other[1]) < 5:
                        found.append(near)
        uniq = []
        for q in found:
            if all(math.hypot(q['x'] - r['x'], q['y'] - r['y']) > 1 for r in uniq):
                uniq.append(q)
        loc, how = (uniq[0], 'leader') if len(uniq) == 1 else (None, 'ambiguous' if uniq else None)
        if not uniq:
            near = min(places, key=lambda q: max(sb[0] - q['x'], q['x'] - sb[2], 0) + max(sb[1] - q['y'], q['y'] - sb[3], 0), default=None)
            if near is not None and max(sb[0] - near['x'], near['x'] - sb[2], 0) + max(sb[1] - near['y'], near['y'] - sb[3], 0) < 12:
                loc, how = near, 'adjacent'
        res.append({'stack': k, 'box': [round(v, 2) for v in sb], 'units': st, 'location': loc, 'located_by': how,
                    'candidates': [{'x': q['x'], 'y': q['y']} for q in uniq] if len(uniq) > 1 else []})
    json.dump({'page_size_pt': [W, H], 'stacks': res}, open(out, 'w'), indent=1, ensure_ascii=False)
    n_units = sum(len(s['units']) for s in res)
    n_loc = sum(len(s['units']) for s in res if s['location'])
    print(json.dumps({'frames': len(frames), 'stacks': len(res), 'units_located': f'{n_loc}/{n_units}', 'places': len(places),
                      'leaders': len(leaders)}))
    if debug:
        import numpy as np, cv2
        k = 2.0
        img = np.array(page.render(scale=k).to_pil().convert('RGB'))[:, :, ::-1].copy()
        for s in res:
            sb = s['box']
            c = (0, 160, 0) if s['location'] else (0, 0, 255)
            cv2.rectangle(img, (int(sb[0] * k), int(sb[1] * k)), (int(sb[2] * k), int(sb[3] * k)), c, 2)
            if s['location']:
                cv2.line(img, (int(sb[0] * k), int(sb[1] * k)), (int(s['location']['x'] * k), int(s['location']['y'] * k)), (0, 160, 0), 2)
                cv2.circle(img, (int(s['location']['x'] * k), int(s['location']['y'] * k)), 8, (0, 160, 0), 2)
        cv2.imwrite(debug, img)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf')
    ap.add_argument('--out', required=True)
    ap.add_argument('--debug', default=None, help='a PNG with the stacks and their leaders drawn')
    a = ap.parse_args()
    main(a.pdf, a.out, a.debug)
