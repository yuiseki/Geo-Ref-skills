"""Control points from the latitude and longitude ticks around a map's frame, read from a vector PDF.

    python scripts/graticule_gcps.py map.pdf --dpi 150 --box-px x0 y0 x1 y1 --out answer.json [--method affine]

Some maps have no town a gazetteer places well enough, and print their graticule instead: UNDOF's maps of the
Golan (2025) mark every 5 minutes on all four sides of the frame, with a short tick and a label such as 35°50'E
(down the page on the left and right). The labels are in the text layer, and the ticks are short lines.

- labels: runs of the text layer between spaces and line breaks that read as degrees, minutes, seconds and a
  hemisphere;
- ticks: each label takes the short straight line beside it whose position along the label's edge matches the
  label's middle (within 1.5 pt);
- lines: a meridian joins the ticks of one longitude on two sides; a longitude ticked on one side only (a label
  hidden under the locator globe) runs parallel to the meridians that have two; the same for parallels;
- control points: every crossing of a meridian and a parallel inside the crop, in the crop's pixels.

Straight lines are the map's graticule as far as its projection keeps them straight: over UNDOF's 70 km a
transverse Mercator parallel bends by under 50 m, under a pixel at 150 dpi. The answer is in name-gcps' form, for
the gates (georef-gates) to pass or fail.
"""

import argparse
import ctypes
import json
import math
import re
from pathlib import Path

import pdf_words as pw

GRID = re.compile(r"^(\d{6,7})([EN])$")
LABEL = re.compile(r"^(\d{1,3})°(?:(\d{1,2}(?:\.\d+)?)['′])?(?:(\d{1,2}(?:\.\d+)?)[\"″])?([NSEW])$")


def parse(text):
    """('lon' | 'lat', signed degrees) of a graticule label, ('x' | 'y', metres) of a grid label (a UTM easting of 6
    digits, a northing of 6 or 7, as UNIFIL's 700000E and 3700000N), else None."""
    g = GRID.match(text.strip())
    if g:
        return ("x" if g.group(2) == "E" else "y"), float(g.group(1))
    m = LABEL.match(text.strip())
    if not m:
        return None
    d, mi, s, h = m.groups()
    v = int(d) + float(mi or 0) / 60 + float(s or 0) / 3600
    return ("lat" if h in "NS" else "lon"), (-v if h in "SW" else v)


def labels(cs):
    """Graticule labels of the text layer: runs of characters between spaces and line breaks, with their box and
    whether they are written down the page."""
    out, run = [], []

    def close():
        if run:
            p = parse("".join(c["ch"] for c in run))
            if p:
                box = (min(c["l"] for c in run), min(c["t"] for c in run), max(c["r"] for c in run), max(c["b"] for c in run))
                out.append({"axis": p[0], "value": p[1], "box": box, "down": box[3] - box[1] > box[2] - box[0]})
        run.clear()

    for c in cs:
        if c["ch"].isspace():
            close()
        else:
            run.append(c)
    close()
    return out


def tick_of(label, ticks, along=1.5, reach=8.0, max_len=6.0):
    """The middle of the tick beside a label: a short straight line, across the label's edge (vertical for a
    longitude, horizontal for a latitude), whose position along the edge is the label's middle within `along` pt
    and which lies within `reach` pt of the label's box. None if there is none."""
    l, t, r, b = label["box"]
    mid = ((l + r) / 2, (t + b) / 2)
    best = None
    for (x0, y0), (x1, y1) in ticks:
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        if math.hypot(dx, dy) > max_len:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if label["axis"] == "lon":
            if dx > 0.3 * dy or abs(cx - mid[0]) > along:
                continue
            off = abs(cx - mid[0])
        else:
            if dy > 0.3 * dx or abs(cy - mid[1]) > along:
                continue
            off = abs(cy - mid[1])
        gap = math.hypot(max(l - cx, cx - r, 0.0), max(t - cy, cy - b, 0.0))
        if gap <= reach and (best is None or (off, gap) < best[0]):
            best = ((off, gap), (round(cx, 6), round(cy, 6)))
    return best[1] if best else None


def grid_line_of(label, segs, along=1.5, min_len=100.0):
    """(point, direction) of the long straight line through a grid label's middle (UNIFIL draws its grid lines across
    the map and writes each label on its line in the margin): vertical for an easting, horizontal for a northing,
    passing within `along` pt of the label's middle. None if there is none."""
    l, t, r, b = label["box"]
    mx, my = (l + r) / 2, (t + b) / 2
    best = None
    for p, q in segs:
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = math.hypot(dx, dy)
        if n < min_len:
            continue
        if label["axis"] == "x":
            if abs(dx) > 0.05 * abs(dy):
                continue
            off = abs(p[0] + (my - p[1]) * dx / dy - mx)
            d = (dx / n, dy / n) if dy > 0 else (-dx / n, -dy / n)
        else:
            if abs(dy) > 0.05 * abs(dx):
                continue
            off = abs(p[1] + (mx - p[0]) * dy / dx - my)
            d = (dx / n, dy / n) if dx > 0 else (-dx / n, -dy / n)
        if off <= along and (best is None or off < best[0]):
            best = (off, (p, (round(d[0], 9) + 0.0, round(d[1], 9) + 0.0)))
    return best[1] if best else None


def lines(marks):
    """[(axis, value, point, direction)]: a line through the two ticks of one value farthest apart; a value with one
    tick, parallel to the mean direction of its axis' two-tick lines (none if there are none)."""
    by = {}
    for axis, v, p in marks:
        by.setdefault((axis, round(v, 9)), (axis, v, []))[2].append(p)
    out, dirs = [], {"lon": [], "lat": []}
    for axis, v, ps in by.values():
        if len(ps) >= 2:
            a, b = max(((p, q) for p in ps for q in ps), key=lambda pq: math.dist(*pq))
            d = (b[0] - a[0], b[1] - a[1])
            if (axis == "lon" and d[1] < 0) or (axis == "lat" and d[0] < 0):
                d = (-d[0], -d[1])
            n = math.hypot(*d)
            dirs[axis].append((d[0] / n, d[1] / n))
            out.append((axis, v, a, (d[0] / n, d[1] / n)))
    for axis, v, ps in by.values():
        if len(ps) == 1 and dirs[axis]:
            dx = sum(d[0] for d in dirs[axis]) / len(dirs[axis])
            dy = sum(d[1] for d in dirs[axis]) / len(dirs[axis])
            out.append((axis, v, ps[0], (dx / math.hypot(dx, dy), dy / math.hypot(dx, dy))))
    return out


def crossings(ls, zone=None):
    """[(x, y, lon, lat)] where each meridian crosses each parallel, and where each grid easting crosses each grid
    northing, turned into degrees by the UTM zone ('36N'); grid lines give nothing without a zone."""
    out = []
    for xa, ya in (("lon", "lat"), ("x", "y")):
        if xa == "x" and not zone:
            continue
        to_deg = utm(zone) if xa == "x" else None
        for a1, u, p, d in ls:
            if a1 != xa:
                continue
            for a2, v, q, e in ls:
                if a2 != ya:
                    continue
                den = d[0] * e[1] - d[1] * e[0]
                if abs(den) < 1e-9:
                    continue
                t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
                lon, lat = to_deg(u, v) if to_deg else (u, v)
                out.append((p[0] + t * d[0], p[1] + t * d[1], lon, lat))
    return out


def utm(zone):
    """A function (easting, northing) -> (lon, lat) for a UTM zone such as '36N' (WGS 84)."""
    from pyproj import Transformer

    n, h = int(zone[:-1]), zone[-1].upper()
    t = Transformer.from_crs(f"EPSG:{32600 + n if h == 'N' else 32700 + n}", "EPSG:4326", always_xy=True)
    return lambda e, nn: t.transform(e, nn)


def dms(v, pos, neg):
    h = pos if v >= 0 else neg
    v = abs(v)
    d = int(v + 1e-9)
    m = round((v - d) * 60, 4)
    return f"{d}°{m:g}'{h}"


def to_pixels(pts, dpi, box_px):
    """Crossings (page points) as control points in the pixels of a crop box_px of a rendering at dpi, those inside."""
    k = dpi / 72.0
    x0, y0, x1, y1 = box_px
    out = []
    for x, y, lon, lat in pts:
        c, r = x * k - x0, y * k - y0
        if 0 <= c <= x1 - x0 and 0 <= r <= y1 - y0:
            out.append({"col": round(c, 3), "row": round(r, 3), "lon": lon, "lat": lat,
                        "name": f"{dms(lon, 'E', 'W')} {dms(lat, 'N', 'S')}"})
    return out


def straight(pts, tol=0.3):
    """(first, last) of a path whose every point lies within tol pt of the line through its ends, else None."""
    if len(pts) < 2 or pts[0] == pts[-1]:
        return None
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    n = math.hypot(x1 - x0, y1 - y0)
    if all(abs((x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)) / n <= tol for x, y in pts):
        return pts[0], pts[-1]
    return None


def straight_lines(page):
    """Straight lines of the page as (first, last) points, as shown (origin top left), inside forms too: the ticks
    (two points) and the grid lines (UNIFIL: one line of 12 to 15 points across the map)."""
    import pypdfium2.raw as R

    rot, W0, H0, x0, y0 = pw.page_frame(page)
    out = []
    for o, outer in pw.objects(page):
        if o.type != R.FPDF_PAGEOBJ_PATH:
            continue
        n = R.FPDFPath_CountSegments(o.raw)
        if not 2 <= n <= 64:
            continue
        mm = o.get_matrix()
        m = pw.compose(outer, (mm.a, mm.b, mm.c, mm.d, mm.e, mm.f))
        pts, ok = [], True
        for i in range(n):
            s = R.FPDFPath_GetPathSegment(o.raw, i)
            if i and R.FPDFPathSegment_GetType(s) != R.FPDF_SEGMENT_LINETO:
                ok = False
                break
            x, y = ctypes.c_float(), ctypes.c_float()
            R.FPDFPathSegment_GetPoint(s, ctypes.byref(x), ctypes.byref(y))
            pts.append(pw.display(*pw.apply(m, x.value, y.value), rot, W0, H0, x0, y0))
        line = straight(pts) if ok else None
        if line:
            out.append(line)
    return out


def main():
    import pypdfium2 as pdfium

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=float, default=150.0)
    ap.add_argument("--box-px", type=float, nargs=4, required=True, help="the crop of the rendering at dpi")
    ap.add_argument("--method", default="affine")
    ap.add_argument("--min-gcps", type=int, default=12)
    ap.add_argument("--utm-zone", default=None, help="the UTM zone of a grid labelled in metres, as 36N")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    page = pdfium.PdfDocument(a.pdf)[a.page - 1]
    labs = labels(pw.chars(a.pdf, a.page))
    segs = straight_lines(page)
    marks = [(g["axis"], g["value"], t) for g in labs if g["axis"] in ("lon", "lat") for t in [tick_of(g, segs)] if t]
    grid = [(g["axis"], g["value"], *gl) for g in labs if g["axis"] in ("x", "y") for gl in [grid_line_of(g, segs)] if gl]
    # one grid line per value (a label on each side of the map finds the same line)
    grid = list({(ax, v): (ax, v, p, d) for ax, v, p, d in grid}.values())
    gcps = to_pixels(crossings(lines(marks) + grid, zone=a.utm_zone), a.dpi, a.box_px)
    x0, y0, x1, y1 = a.box_px
    info = {"image": {"width": round(x1 - x0), "height": round(y1 - y0)},
            "tool": {"name": "graticule-gcps", "words_from": "pdf"},
            "labels": len(labs), "ticked": len(marks), "grid_lines": len(grid), "utm_zone": a.utm_zone}
    if len(gcps) < a.min_gcps:
        ans = {"status": "failed", "reason": f"{len(gcps)} graticule crossings in the crop (need {a.min_gcps})", **info}
    else:
        ans = {"status": "ok", "method": a.method, "crs": "EPSG:4326", "gcps": gcps, **info}
    Path(a.out).write_text(json.dumps(ans, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in ans.items() if k != "gcps"} | {"gcps": len(gcps)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
