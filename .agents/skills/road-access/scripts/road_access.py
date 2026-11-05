"""Road access constraints maps (WFP Logistics Cluster, South Sudan) as data: the table of roads and their status,
and the roads drawn on the map in the status colours.

    python scripts/road_access.py map.pdf --out roads.json

The map is read from the PDF's drawing and text layers, with no model. The table beside the map gives each road a
number or code, its two ends ("From - To"), the largest truck it takes and its status, as the colour of its cell.
The status colours (legend): green, the road is passable; yellow or orange, passable with difficulties; red, not
passable. Positions are page points, origin top left, as the page is shown.
"""
import argparse
import colorsys
import json
import re

import pdf_words as pw

ID = re.compile(r"^([A-Z]\d{2}|\d{1,3})$")
DASH = re.compile(r"\s*[-\u2010-\u2015]\s*")


def status_of(rgb):
    """The status a colour stands for, by its hue; None for greys and colours of no status."""
    if rgb is None:
        return None
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    if s < 0.2 or v < 0.5:
        return None
    deg = h * 360
    if 280 <= deg <= 340:  # pink
        return "last-mile delivery by land cruiser"
    if deg < 20 or deg > 340:
        return "not passable"
    if deg < 70:
        return "passable with difficulties"
    if 70 <= deg < 170:
        return "passable"
    return None


def id_columns(words, min_rows=8, tol=1.5):
    """Words that look like road numbers or codes and stand in a column (the table), as lists sorted by y."""
    ids = sorted((x for x in words if x["kind"] == "word" and ID.match(x["text"])), key=lambda x: x["x"] - x["w"] / 2)
    cols, cur = [], []
    for x in ids:
        if cur and abs((x["x"] - x["w"] / 2) - (cur[-1]["x"] - cur[-1]["w"] / 2)) > tol:
            cols.append(cur)
            cur = []
        cur.append(x)
    if cur:
        cols.append(cur)
    return [sorted(c, key=lambda x: x["y"]) for c in cols if len(c) >= min_rows]


def table_rows(words, fills, min_rows=8):
    cols = id_columns(words, min_rows)
    starts = sorted(c[0]["x"] - c[0]["w"] / 2 for c in cols)
    trucks = [x for x in words if x["kind"] == "word" and x["text"] == "Truck"]
    out = []
    for c in cols:
        left = c[0]["x"] + c[0]["w"] / 2
        right = min([s for s in starts if s > left] + [float("inf")])
        th = [t for t in trucks if left < t["x"] < right]
        truck_x = th[0]["x"] - th[0]["w"] / 2 - 2 if th else right
        rows = []
        for i in c:
            band = [x for x in words if x["kind"] == "word" and x is not i and abs(x["y"] - i["y"]) < 0.5 * i["h"]
                    and left < x["x"] < right]
            road = sorted((x for x in band if x["x"] < truck_x), key=lambda x: x["x"])
            truck = " ".join(x["text"] for x in sorted(band, key=lambda x: x["x"]) if x["x"] >= truck_x) or None
            if not road:
                continue
            text = " ".join(x["text"] for x in road)
            if not re.search(r"[A-Za-z]{2}", text):
                continue  # symbol glyphs, not a road
            ends = [e.strip() for e in DASH.split(text) if e.strip()]
            cx = sum(x["x"] for x in road) / len(road)
            under = [f for f in fills if f["fill"] and f["box"][0] <= cx <= f["box"][2] and f["box"][1] <= i["y"] <= f["box"][3]]
            # the cell is the smallest fill of a status colour under it: a box over the whole table may be drawn
            # after the cells (18 September 2026), and pieces of the map's grey background reach under it
            under.sort(key=lambda f: (status_of(f["fill"]) is None, (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1])))
            colour = under[0]["fill"] if under else None
            rows.append({"id": i["text"], "road": text, "from": ends[0], "via": ends[1:-1], "to": ends[-1] if len(ends) > 1 else None,
                        "truck": truck, "status": status_of(colour), "colour": colour, "x": i["x"], "y": i["y"]})
        # a column of the table has its cells coloured; numbers on the map that line up by chance do not
        if rows and sum(1 for r in rows if r["status"]) >= 0.5 * len(rows):
            out += rows
    return out


def paths(page):
    """Every path on the page (forms included) with its fill and stroke colours, its box (left, top, right, bottom)
    and its points, as shown (pdf_words.page_frame)."""
    import ctypes
    import pypdfium2.raw as R

    def col(fn, o):
        r, g, b, a = (ctypes.c_uint() for _ in range(4))
        return (r.value, g.value, b.value) if fn(o, *(ctypes.byref(v) for v in (r, g, b, a))) else None

    rot, W0, H0, x0, y0 = pw.page_frame(page)
    out = []
    for o in page.get_objects(max_depth=16):
        if o.type != R.FPDF_PAGEOBJ_PATH:
            continue
        mode, st = ctypes.c_int(), ctypes.c_int()
        R.FPDFPath_GetDrawMode(o.raw, ctypes.byref(mode), ctypes.byref(st))
        m = o.get_matrix()
        pts = []
        for i in range(R.FPDFPath_CountSegments(o.raw)):
            s = R.FPDFPath_GetPathSegment(o.raw, i)
            x, y = ctypes.c_float(), ctypes.c_float()
            R.FPDFPathSegment_GetPoint(s, ctypes.byref(x), ctypes.byref(y))
            X, Y = m.a * x.value + m.c * y.value + m.e, m.b * x.value + m.d * y.value + m.f
            pts.append((R.FPDFPathSegment_GetType(s), *pw.display(X, Y, rot, W0, H0, x0, y0)))
        w = ctypes.c_float()
        R.FPDFPageObj_GetStrokeWidth(o.raw, ctypes.byref(w))
        l, b, r, t = o.get_bounds()
        out.append({"fill": col(R.FPDFPageObj_GetFillColor, o.raw) if mode.value else None,
                    "stroke": col(R.FPDFPageObj_GetStrokeColor, o.raw) if st.value else None,
                    "width": w.value, "box": pw.display_box(l, b, r, t, rot, W0, H0, x0, y0), "pts": pts})
    return out


def road_lines(ps):
    """The roads drawn in the status colours, as {status, colour, width, parts: [[(x, y), ...]]}: for each status
    the brightest colour drawn in it (a road may lie on a darker casing of the same hue), at the width its paths
    mostly have (the legend's swatches are wider), with at least 3 points."""
    import collections
    by = collections.defaultdict(list)
    for p in ps:
        st = status_of(p["stroke"])
        if st and len(p["pts"]) >= 3:
            by[st].append(p)
    out = []
    for st, group in by.items():
        colour = max({p["stroke"] for p in group}, key=lambda c: (colorsys.rgb_to_hsv(*(v / 255 for v in c))[2],
                                                                  sum(len(p["pts"]) for p in group if p["stroke"] == c)))
        mine = [p for p in group if p["stroke"] == colour]
        width = collections.Counter(round(p["width"], 2) for p in mine).most_common(1)[0][0]
        for p in mine:
            if abs(p["width"] - width) > 0.01:
                continue
            parts = []
            for t, x, y in p["pts"]:
                if t == 2 or not parts:  # pdfium FPDF_SEGMENT_MOVETO (0 lineto, 1 bezierto)
                    parts.append([])
                parts[-1].append((x, y))
            parts = [q for q in parts if len(q) >= 2]
            if parts:
                out.append({"status": st, "colour": colour, "width": width, "parts": parts})
    return out


def seg_dist(px, py, a, b):
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L))
    return ((px - x0 - t * dx) ** 2 + (py - y0 - t * dy) ** 2) ** 0.5


def line_dist(px, py, line):
    return min(seg_dist(px, py, a, b) for part in line["parts"] for a, b in zip(part, part[1:]))


def link(lines, words, rows, max_d=8.0):
    """Each road label on the map (a word that is a row's number or code, not in the table) goes to the nearest
    line within max_d; each line gets the labels, the rows they name, and whether their status agrees with its
    colour (None if no label)."""
    by_id = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)
    in_table = {(r["x"], r["y"]) for r in rows if "x" in r}
    for ln in lines:
        ln["ids"], ln["rows"] = [], []
    for wd in words:
        if wd["kind"] != "word" or wd["text"] not in by_id or (wd["x"], wd["y"]) in in_table:
            continue
        d, ln = min(((line_dist(wd["x"], wd["y"], ln), i) for i, ln in enumerate(lines)), default=(None, None))
        if d is None or d > max_d:
            continue
        lines[ln]["ids"].append(wd["text"])
        lines[ln]["rows"] += by_id[wd["text"]]
    for ln in lines:
        ln["agrees"] = all(r["status"] == ln["status"] for r in ln["rows"]) if ln["rows"] else None
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(a.pdf)[a.page - 1]
    ps = paths(page)
    words = pw.words(pw.chars(a.pdf, a.page))
    rows = table_rows(words, [p for p in ps if p["fill"]])
    lines = link(road_lines(ps), words, rows)
    for ln in lines:
        ln["rows"] = [r["id"] for r in ln["rows"]]
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"table": rows, "lines": lines}, f, ensure_ascii=False)
    print(json.dumps({"rows": len(rows), "no_status": sum(1 for r in rows if not r["status"]), "lines": len(lines),
                      "labelled": sum(1 for x in lines if x["ids"]), "disagree": sum(1 for x in lines if x["agrees"] is False),
                      "rows_on_map": len({i for x in lines for i in x["ids"]})}))


if __name__ == "__main__":
    main()
