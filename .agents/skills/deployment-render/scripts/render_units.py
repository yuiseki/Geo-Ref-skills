"""Draw a deployment GeoJSON (the unit points of deployment-geojson) as military map symbols on a reference map.

    uvx --with numpy --with opencv-python-headless --with cairosvg python scripts/render_units.py \
        deployment.geojson --reference ref_dir --symbols symbols_dir --out out.jpg

ref_dir holds reference.png and reference.json (its "geotransform": web mercator x0, dx, 0, y0, 0, dy) as a tile
renderer writes them. symbols_dir holds symbol SVGs named by arm (infantry.svg, medical.svg, ...) and sources.json
(per arm: title, licence, artist, url), as fetch_symbols.py writes them. A unit whose arm has no symbol is drawn as
a plain frame with the letters written inside it (UNMO, FPU, MP), as the UN does. The size of the unit is drawn above
the frame (platoon three dots, company one bar, battalion two, brigade a cross, division two), units stacked at one
place side by side from the point. The credits of the symbols and of the map are written into the picture.
"""

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

ORIGIN = 20037508.342789244
# the arm a unit's "arm" property names -> the symbol file; headquarters of any rank share one
SYMBOL_OF = {"infantry": "infantry", "medical": "medical", "engineer": "engineer", "signal": "signal",
             "military police": "military police", "artillery": "artillery", "aviation (rotary wing)": "aviation",
             "aviation (fixed wing)": "aviation", "headquarters": "headquarters", "sector headquarters": "headquarters",
             "force headquarters": "headquarters"}
LETTERS = {"military police": "MP", "aviation (rotary wing)": "AVN", "aviation (fixed wing)": "AVN", "headquarters": "HQ", "military observers": "UNMO", "formed police unit": "FPU", "individual police officers": "IPO",
           "quick reaction force": "QRF", "special forces": "SF", "special operations forces": "SOF",
           "explosive ordnance disposal": "EOD", "riverine": "RIV"}
MARKS = {"platoon": (3, "dot"), "section": (2, "dot"), "company": (1, "bar"), "battalion": (2, "bar"),
         "regiment": (3, "bar"), "brigade": (1, "x"), "division": (2, "x")}
FILL, EDGE = (255, 225, 125), (0, 0, 0)  # BGR of the light blue friendly frame (APP-6), and its outline


def to_mercator(lon, lat):
    x = lon * ORIGIN / 180.0
    y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / math.pi * ORIGIN
    return x, y


def symbol_key(arm):
    return SYMBOL_OF.get(arm)


def mark_geometry(echelon):
    """(count, kind) of the size mark above the frame, or None."""
    return MARKS.get(echelon)


def stack_groups(features, gt):
    """The units grouped by the pixel they are drawn at (rounded), in the order they first appear."""
    groups = {}
    for f in features:
        x, y = to_mercator(*f["geometry"]["coordinates"])
        px = ((x - gt[0]) / gt[1], (y - gt[3]) / gt[5])
        groups.setdefault((round(px[0]), round(px[1])), []).append(f["properties"])
    return groups


def load_symbol(path, height):
    import cairosvg
    import cv2 as _cv
    w = int(round(height * 1.5))
    png = cairosvg.svg2png(url=str(path), output_width=w, output_height=height)
    im = _cv.imdecode(np.frombuffer(png, np.uint8), _cv.IMREAD_UNCHANGED)
    if im.ndim == 3 and im.shape[2] == 3:  # a symbol that fills its box has no alpha channel
        im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    return im  # BGRA


def paste(canvas, sym, x, y):
    """Lay a BGRA symbol on a BGR canvas with its top left at (x, y), clipped to the canvas."""
    h, w = sym.shape[:2]
    H, W = canvas.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    s = sym[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.float32) / 255.0
    canvas[y0:y1, x0:x1] = (s[..., :3] * a + canvas[y0:y1, x0:x1] * (1 - a)).astype(np.uint8)


def blank_frame(height, letters=None):
    w = int(round(height * 1.5))
    im = np.zeros((height, w, 4), np.uint8)
    cv2.rectangle(im, (1, 1), (w - 2, height - 2), (*FILL, 255), -1)
    cv2.rectangle(im, (1, 1), (w - 2, height - 2), (*EDGE, 255), 2)
    if letters:
        scale = 0.45 * height / 24
        (tw, th), _ = cv2.getTextSize(letters, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        cv2.putText(im, letters, ((w - tw) // 2, (height + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (*EDGE, 255), 1, cv2.LINE_AA)
    return im


def draw_marks(canvas, echelon, x, y, w):
    """The size mark centred above a frame whose top left is (x, y) and width w."""
    m = mark_geometry(echelon)
    if not m:
        return
    n, kind = m
    cx, top = x + w // 2, y - 3
    gap = max(5, w // 8)
    xs = [cx + int((i - (n - 1) / 2) * gap) for i in range(n)]
    for px in xs:
        if kind == "dot":
            cv2.circle(canvas, (px, top - 3), 2, EDGE, -1, cv2.LINE_AA)
        elif kind == "bar":
            cv2.line(canvas, (px, top - 1), (px, top - 8), EDGE, 2, cv2.LINE_AA)
        else:
            d = 4
            cv2.line(canvas, (px - d, top - 1), (px + d, top - 9), EDGE, 2, cv2.LINE_AA)
            cv2.line(canvas, (px - d, top - 9), (px + d, top - 1), EDGE, 2, cv2.LINE_AA)


def text(canvas, s, org, scale=0.45, colour=(40, 40, 40)):
    cv2.putText(canvas, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(canvas, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 1, cv2.LINE_AA)


def render(features, ref, gt, symbols_dir, height=26):
    canvas = ref.copy()
    cache = {}

    used = set()

    def symbol(arm):
        key = symbol_key(arm)
        path = Path(symbols_dir) / f"{key.replace(' ', '_')}.svg" if key else None
        if path and path.exists():
            if key not in cache:
                cache[key] = load_symbol(path, height)
            used.add(key)  # only a symbol that was drawn is credited
            return cache[key]
        return blank_frame(height, LETTERS.get(arm))

    for (x, y), units in stack_groups(features, gt).items():
        w = int(round(height * 1.5))
        cv2.circle(canvas, (x, y), 3, (0, 0, 255), -1, cv2.LINE_AA)
        ox, oy = x + 8, y - height - 8
        cv2.line(canvas, (x, y), (ox, oy + height), (0, 0, 0), 1, cv2.LINE_AA)
        cell, per_row = max(w + 6, 62), 5
        if ox + min(len(units), per_row) * cell > canvas.shape[1]:
            ox = max(0, canvas.shape[1] - min(len(units), per_row) * cell)  # kept inside the picture
        for i, p in enumerate(units):
            sx = ox + (i % per_row) * cell
            oy = y - height - 8 + (i // per_row) * (height + 30)
            paste(canvas, symbol(p.get("arm")), sx, oy)
            draw_marks(canvas, p.get("echelon"), sx, oy, w)
            if p.get("label"):
                text(canvas, str(p["label"])[:12], (sx, oy + height + 12), 0.36)
    return canvas, used


def credit_lines(used, symbols_dir):
    src = {}
    p = Path(symbols_dir) / "sources.json"
    if p.exists():
        src = json.loads(p.read_text(encoding="utf-8"))
    lines = ["Map: Based on United Nations map. Background: (c) OpenStreetMap contributors. No warranty, may be wrong."]
    by = sorted({(src[k]["artist"], src[k]["licence"]) for k in used if k in src})
    if by:
        lines.append("Symbols: Wikimedia Commons, " + "; ".join(f"{a}, {l}" for a, l in by) + " (https://commons.wikimedia.org)")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("geojson")
    ap.add_argument("--reference", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--height", type=int, default=26)
    a = ap.parse_args()
    fs = json.loads(Path(a.geojson).read_text(encoding="utf-8"))["features"]
    ref = cv2.imread(str(Path(a.reference) / "reference.png"))
    gt = json.loads((Path(a.reference) / "reference.json").read_text(encoding="utf-8"))["geotransform"]
    ref = cv2.addWeighted(ref, 0.7, np.full_like(ref, 255), 0.3, 0)
    canvas, used = render(fs, ref, gt, a.symbols, a.height)
    H = canvas.shape[0]
    for i, line in enumerate(credit_lines(used, a.symbols)):
        text(canvas, line, (10, H - 12 - 18 * (1 - i)), 0.42)
    cv2.imwrite(a.out, canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(json.dumps({"out": a.out, "units": len(fs), "symbols": sorted(used)}))


if __name__ == "__main__":
    main()
