"""Draw the points of a deployment GeoJSON (level 6) on OpenStreetMap, coloured by arm, labelled by the unit's label.

    uvx --with numpy --with opencv-python-headless --with pillow python docs/examples/make_units_overlay.py \
        deployment.geojson out.jpg [--style osm-liberty] [--width 1700] [--margin 0.15]
"""

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents/skills/georef-gates/scripts"))
sys.path.insert(0, str(ROOT / ".agents/skills/tile-reference/scripts"))
import fetch_reference as fr  # noqa: E402
import webmercator as wm  # noqa: E402

# BGR; one colour per arm, the same on every map
COLOURS = {"infantry": (60, 60, 220), "engineer": (30, 140, 240), "signal": (200, 120, 30), "medical": (60, 170, 60),
           "military police": (160, 60, 160), "formed police unit": (120, 120, 0), "aviation (rotary wing)": (0, 200, 220),
           "riverine": (200, 200, 40)}
HQ = (0, 0, 0)


def colour(arm):
    return HQ if arm and "headquarters" in arm else COLOURS.get(arm, (128, 128, 128))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("geojson")
    ap.add_argument("out")
    ap.add_argument("--style", default="osm-liberty")
    ap.add_argument("--width", type=int, default=1700)
    ap.add_argument("--margin", type=float, default=0.15)
    ap.add_argument("--cache", default=str(ROOT / "tmp/tiles"))
    a = ap.parse_args()
    fs = json.loads(Path(a.geojson).read_text(encoding="utf-8"))["features"]
    ll = np.array([f["geometry"]["coordinates"] for f in fs])
    m = np.column_stack(wm.lonlat_to_mercator(ll[:, 0], ll[:, 1]))
    lo, hi = m.min(axis=0), m.max(axis=0)
    span = hi - lo
    lo, hi = lo - a.margin * span, hi + a.margin * span
    zoom = max(1, round(math.log2(a.width * (2 * wm.ORIGIN) / (float(hi[0] - lo[0]) * 256))))
    (w, s), (e, n) = (wm.mercator_to_lonlat(*lo), wm.mercator_to_lonlat(*hi))
    out_dir = Path(a.out).parent / (Path(a.out).stem + "-ref")
    fr.build(a.style, zoom, (w, s, e, n), a.cache, out_dir)
    ref = cv2.imread(str(out_dir / "reference.png"))
    gt = json.loads((out_dir / "reference.json").read_text(encoding="utf-8"))["geotransform"]
    ref = cv2.addWeighted(ref, 0.7, np.full_like(ref, 255), 0.3, 0)
    px = np.column_stack([(m[:, 0] - gt[0]) / gt[1], (m[:, 1] - gt[3]) / gt[5]])
    # units stacked at one place share a point: one dot, the first unit's label and how many more
    groups = {}
    for (x, y), f in zip(px, fs):
        groups.setdefault((round(float(x)), round(float(y))), []).append(f["properties"])
    for (x, y), ps in groups.items():
        c = colour(ps[0].get("arm"))
        cv2.circle(ref, (x, y), 10, (255, 255, 255), -1)
        cv2.circle(ref, (x, y), 7, c, -1)
        t = (ps[0].get("label") or "")[:14] + (f" +{len(ps) - 1}" if len(ps) > 1 else "")
        if t.strip():
            org = (x + 11, y - 7)
            cv2.putText(ref, t, org, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 3, cv2.LINE_AA)
            cv2.putText(ref, t, org, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 40), 1, cv2.LINE_AA)
    arms = sorted({f["properties"].get("arm") for f in fs if f["properties"].get("arm")}, key=str)
    y0 = 20
    for arm in arms:
        cv2.rectangle(ref, (14, y0 - 4), (240, y0 + 20), (255, 255, 255), -1)
        cv2.circle(ref, (28, y0 + 8), 6, colour(arm), -1)
        cv2.putText(ref, arm, (42, y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 40), 1, cv2.LINE_AA)
        y0 += 24
    cv2.imwrite(a.out, ref, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(json.dumps({"out": a.out, "zoom": zoom, "size": list(ref.shape[1::-1]), "points": len(fs)}))


if __name__ == "__main__":
    main()
