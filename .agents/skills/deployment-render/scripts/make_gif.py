"""A time series of deployment GeoJSON files as an animated GIF of military symbols on one reference map.

    uvx --with numpy --with opencv-python-headless --with cairosvg --with pillow python scripts/make_gif.py \
        a.geojson b.geojson ... --reference ref_dir --symbols symbols_dir --out series.gif [--width 1100] [--ms 1200]

Every frame is drawn on the same reference (it must reach every file's points) so that a unit that stays stays put.
Frames are ordered by the date of the map (the collection's "map_date", else the features' "date"), and a date given
twice keeps its first file. Each frame is captioned with the date, the number of units drawn, and a mark when the
map's own answer did not pass every gate (its points were used one by one).
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import render_units as ru


def map_date(doc):
    d = doc.get("map_date")
    if not d and doc.get("features"):
        d = doc["features"][0]["properties"].get("date")
    return str(d or "")


def frames_of(docs):
    """(date, features) in date order, one per date."""
    seen, out = set(), []
    for doc in sorted(docs, key=map_date):
        d = map_date(doc)
        if d in seen or not doc.get("features"):
            continue
        seen.add(d)
        out.append((d, doc["features"]))
    return out


def caption(date, features):
    s = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) >= 8 else date
    mark = "" if all(f["properties"].get("map_ok", True) for f in features) else "  (points checked one by one)"
    return f"{s}   {len(features)} units drawn{mark}"


def main():
    from PIL import Image
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("geojson", nargs="+")
    ap.add_argument("--reference", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1100)
    ap.add_argument("--height", type=int, default=40, help="symbol height in pixels before the picture is scaled")
    ap.add_argument("--ms", type=int, default=1200)
    a = ap.parse_args()
    docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in a.geojson]
    ref = cv2.imread(str(Path(a.reference) / "reference.png"))
    gt = json.loads((Path(a.reference) / "reference.json").read_text(encoding="utf-8"))["geotransform"]
    ref = cv2.addWeighted(ref, 0.7, np.full_like(ref, 255), 0.3, 0)
    pics = []
    for date, fs in frames_of(docs):
        canvas, used = ru.render(fs, ref, gt, a.symbols, a.height)
        H = canvas.shape[0]
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 46), (255, 255, 255), -1)
        cv2.putText(canvas, caption(date, fs), (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2, cv2.LINE_AA)
        for i, line in enumerate(ru.credit_lines(used, a.symbols)):
            ru.text(canvas, line, (10, H - 12 - 18 * (1 - i)), 0.42)
        k = a.width / canvas.shape[1]
        canvas = cv2.resize(canvas, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        pics.append(Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)).quantize(colors=128, dither=Image.Dither.NONE))
    pics[0].save(a.out, save_all=True, append_images=pics[1:], duration=a.ms, loop=0, optimize=True)
    print(json.dumps({"out": a.out, "frames": len(pics)}))


if __name__ == "__main__":
    main()
