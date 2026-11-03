"""Guess where a map is from the place names printed on it.

    python scripts/place_hint.py image.png --out hint.json [--countrycodes jp] [--cache tmp/nominatim]

1. Read words with tesseract (ocr_words.py), at several angles since the map may be rotated, and keep those that
   look like place names (clean_name).
2. Look each name up on the self-hosted Nominatim (nominatim.py, cached, one request at a time).
3. A name usually has candidates all over the country. Keep the place where the most different names have a
   candidate within radius_km of each other, and write their extent plus a margin as the hint bbox.

Fewer than min_support agreeing names is a declared failure ("status": "failed"), not a guess. Maps without
text (only rivers or railways) cannot be placed this way.
"""

import argparse
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

STOP = {"CHOME", "HOME", "CHOM", "STATION", "BUS", "TERMINAL", "PARK", "EXIT", "NORTH", "SOUTH", "EAST", "WEST", "GATE", "CITY",
        "TOWN", "LINE", "ROUTE", "HOSPITAL", "SCHOOL", "BRIDGE", "RIVER"}
LATIN = re.compile(r"^[A-Za-z][A-Za-z\-]+[A-Za-z]$")
CJK = re.compile(r"^[぀-ヿ㐀-鿿]+$")
KANA_ONLY = re.compile(r"^[぀-ヿ]+$")


def clean_name(raw):
    """A word worth looking up, or None. Latin: letters and inner hyphens, at least 4 letters, upper case or
    capitalised (OCR noise is often mixed case), not a generic word. CJK: at least 2 characters with a kanji."""
    t = raw.strip().strip(".,;:()[]{}'\"")
    if LATIN.match(t):
        letters = t.replace("-", "")
        if len(letters) < 4 or t.upper() != t and not (t[0].isupper() and t[1:].islower()):
            return None
        if any(part in STOP for part in t.upper().split("-")):
            return None
        return t
    if CJK.match(t) and len(t) >= 2 and not KANA_ONLY.match(t):
        return t
    return None


def norm(t):
    """Compare names regardless of case, hyphens, spaces and long-vowel marks (Jimbōchō = JIMBOCHO)."""
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[\s\-‐‑・·'’]", "", t).casefold()


def exact_hits(name, hits):
    """Nominatim matches loosely ("DORI" finds "Showa-dori avenue"); keep a hit only when one of its names
    (namedetails: name, name:en, name:ja-Latn, ...) is the name itself. Seen on 2026-11-03: fragments such
    as DORI, HOME and ASHI out-voted real names and put an Osaka map 4 degrees east."""
    want = norm(name)
    keep = []
    for h in hits:
        names = list((h.get("namedetails") or {}).values()) + [h.get("name") or ""]
        if any(norm(v) == want for v in names if isinstance(v, str)):
            keep.append(h)
    return keep


def haversine_km(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, a)))


def cluster(cands, radius_km=10.0, min_support=3, margin_km=4.0, min_weight=1.5):
    """cands: {name: [{"lon", "lat", "importance", ...}, ...]}. Returns the hint.

    A name found in many places (CHUO, KITA, HIGASHI) says little about where the map is: each name weighs
    1 / (its number of candidates). The place kept is the one with the largest total weight of names agreeing
    within radius_km; it needs at least min_support names and min_weight in total. Seen on 2026-11-03: by count
    alone, CHUO, HIGASHI and KITA put a Sapporo map 7 degrees away."""
    weight = {name: 1.0 / len(cs) for name, cs in cands.items() if cs}
    points = [(name, c) for name, cs in cands.items() for c in cs]
    best = None
    for name, c in points:
        near = {}
        for other, cs in cands.items():
            close = [d for d in cs if haversine_km(c["lon"], c["lat"], d["lon"], d["lat"]) <= radius_km]
            if close:
                near[other] = max(close, key=lambda d: d.get("importance", 0))
        score = (sum(weight[k] for k in near), len(near))
        if best is None or score > best[0]:
            best = (score, near)
    if best is None or best[0][1] < min_support or best[0][0] < min_weight:
        w, n = (0.0, 0) if best is None else best[0]
        return {"status": "failed", "reason": f"support {n} names (need {min_support}), weight {w:.2f} "
                f"(need {min_weight})", "names_looked_up": len(cands)}
    near = best[1]
    lons = [d["lon"] for d in near.values()]
    lats = [d["lat"] for d in near.values()]
    mlat = margin_km / 111.32
    mlon = margin_km / (111.32 * math.cos(math.radians(sum(lats) / len(lats))))
    return {"status": "ok", "bbox": [min(lons) - mlon, min(lats) - mlat, max(lons) + mlon, max(lats) + mlat],
            "support": sorted(near), "matches": {k: {kk: d.get(kk) for kk in ("lon", "lat", "display_name")}
                                                 for k, d in near.items()},
            "weight": best[0][0], "names_looked_up": len(cands), "radius_km": radius_km, "margin_km": margin_km}


def main():
    import nominatim
    import ocr_words

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--out", required=True)
    ap.add_argument("--langs", default="jpn+eng")
    ap.add_argument("--min-conf", type=float, default=70.0)
    ap.add_argument("--countrycodes", default=None, help="limit Nominatim, e.g. jp")
    ap.add_argument("--cache", default="tmp/nominatim")
    ap.add_argument("--radius-km", type=float, default=10.0)
    ap.add_argument("--min-support", type=int, default=3)
    ap.add_argument("--margin-km", type=float, default=4.0)
    ap.add_argument("--min-weight", type=float, default=1.5)
    ap.add_argument("--max-names", type=int, default=40)
    ap.add_argument("--scale", type=float, default=3.0)
    ap.add_argument("--angles", type=float, nargs="*", default=[-45, -30, -15, 0, 15, 30, 45],
                    help="also read the image turned by these angles; a map may be rotated")
    a = ap.parse_args()
    words = ocr_words.read_words(a.image, a.langs, a.scale, angles=a.angles)
    names = []
    for w in sorted(words, key=lambda w: -w["conf"]):
        n = clean_name(w["text"])
        if n and w["conf"] >= a.min_conf and n not in names:
            names.append(n)
    names = names[:a.max_names]
    client = nominatim.Client(a.cache)
    cands = {}
    for n in names:
        hits = exact_hits(n, client.search(n, countrycodes=a.countrycodes, namedetails=True))
        if hits:
            cands[n] = [{"lon": float(h["lon"]), "lat": float(h["lat"]), "importance": float(h.get("importance") or 0),
                         "display_name": h.get("display_name")} for h in hits]
    hint = cluster(cands, a.radius_km, a.min_support, a.margin_km, a.min_weight)
    hint["ocr_words"] = len(words)
    hint["names"] = names
    hint["nominatim"] = {"base": client.base, "requests": client.requests, "cached": client.cached}
    Path(a.out).write_text(json.dumps(hint, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: hint.get(k) for k in ("status", "reason", "bbox", "support")}, ensure_ascii=False))
    sys.exit(0 if hint["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
