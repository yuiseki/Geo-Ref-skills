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


CHOME_NAME = re.compile(r"^([A-Za-z][A-Za-z\-]+[A-Za-z]) (\d{1,2}-CHOME)$", re.IGNORECASE)


def clean_name(raw):
    """A word worth looking up, or None. Latin: letters and inner hyphens, at least 4 letters, upper case or
    capitalised (OCR noise is often mixed case), not a generic word; or such a name with its block number
    ("KANOCHO 3-CHOME"). CJK: at least 2 characters with a kanji. A final "!" after capitals is read as I
    (tesseract reads the italic I of map labels as "!": KAIGANDOR!)."""
    t = raw.strip().strip(".,;:()[]{}'\"")
    if len(t) > 4 and t.endswith("!") and t[:-1].isupper():
        t = t[:-1] + "I"
    m = CHOME_NAME.match(t)
    if m:
        name = clean_name(m.group(1))
        return f"{name} {m.group(2).upper()}" if name else None
    t = t.strip("!")
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
    as DORI, HOME and ASHI out-voted real names and put an Osaka map 4 degrees east.

    A plain district name also matches its numbered blocks ("NINOMIYACHO" matches "Ninomiyacho 3-chome"):
    many districts exist in OpenStreetMap only as their chome blocks, and the map prints the name once over
    several blocks (Kobe, 2026-11-04)."""
    want = norm(name)
    block = re.compile("^" + re.escape(want) + r"\d{1,2}chome$")
    keep = []
    for h in hits:
        names = list((h.get("namedetails") or {}).values()) + [h.get("name") or ""]
        ns = [norm(v) for v in names if isinstance(v, str)]
        if any(v == want or block.match(v) for v in ns):
            keep.append(h)
    return keep


def merge_near(cs, km=2.0):
    """Candidates of one name lying within km of each other are one place (the chome blocks of one district,
    or the nodes and areas OpenStreetMap has for one name): their mean position, the largest importance."""
    groups = []
    for c in cs:
        for g in groups:
            if haversine_km(c["lon"], c["lat"], g[0]["lon"], g[0]["lat"]) <= km:
                g.append(c)
                break
        else:
            groups.append([c])
    return [{**g[0], "lon": sum(c["lon"] for c in g) / len(g), "lat": sum(c["lat"] for c in g) / len(g),
             "importance": max(c.get("importance", 0) for c in g)} for g in groups]


def lookup(client, name, countrycodes=None):
    """Exact hits for a name. A Latin district name is also asked as "<name> 1-chome": districts that exist in
    OpenStreetMap only as their chome blocks are not returned for the bare name (KANOCHO in Kobe, 2026-11-04,
    found only as "Kanocho 3-chome"), while the map prints the bare name over the blocks."""
    # limit 40: Nominatim's ceiling; with 10, a common district name (KAWASAKICHO, seven places) could miss
    # the one on the map
    hits = exact_hits(name, client.search(name, limit=40, countrycodes=countrycodes, namedetails=True))
    if LATIN.match(name):
        more = exact_hits(name, client.search(f"{name} 1-chome", limit=40, countrycodes=countrycodes, namedetails=True))
        seen = {(h.get("lat"), h.get("lon")) for h in hits}
        hits += [h for h in more if (h.get("lat"), h.get("lon")) not in seen]
    return hits


def drop_covered(cands):
    """A label read both as "KANOCHO" and as "KANOCHO 3-CHOME" is one place: keep only the more specific form,
    so that one label does not count twice towards the support and the scale fit."""
    covered = {k.rsplit(" ", 1)[0] for k in cands if CHOME_NAME.match(k)}
    return {k: v for k, v in cands.items() if k not in covered}


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


ORIGIN = 20037508.342789244  # EPSG:3857 half circumference, metres


def lonlat_to_mercator(lon, lat):
    return (math.radians(lon) * 6378137.0,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137.0)


def mercator_to_lonlat(x, y):
    return math.degrees(x / 6378137.0), math.degrees(2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2)


def located_points(words, matches):
    """Each supporting name with where it is printed (its most confident reading) and where Nominatim puts it."""
    pts = {}
    for w in sorted(words, key=lambda w: -w["conf"]):
        n = clean_name(w["text"])
        if n in matches and n not in pts:
            pts[n] = {"name": n, "col": w["col"], "row": w["row"], "lon": matches[n]["lon"], "lat": matches[n]["lat"]}
    return [pts[k] for k in sorted(pts)]


def _fit(pairs, weights=None):
    """Weighted least-squares similarity Z = a z + b over (z, Z) pairs of complex numbers."""
    w = weights or [1.0] * len(pairs)
    sw = sum(w)
    mz = sum(wi * z for wi, (z, _) in zip(w, pairs)) / sw
    mZ = sum(wi * Z for wi, (_, Z) in zip(w, pairs)) / sw
    num = sum(wi * (Z - mZ) * (z - mz).conjugate() for wi, (z, Z) in zip(w, pairs))
    den = sum(wi * abs(z - mz) ** 2 for wi, (z, _) in zip(w, pairs))
    a = num / den
    return a, mZ - a * mz


def scale_from_names(points, width, height, tol_frac=0.06, loose_frac=0.10, min_inliers=4, min_fraction=0.5,
                     min_loose_inliers=5, margin_frac=0.25):
    """The map's scale, rotation and extent from where its names are printed and where they are.

    points: [{"name", "col", "row", "lon", "lat"}], col and row the centre of the printed name in the image.
    Fits a similarity (scale, rotation, shift; no mirror) from image pixels to EPSG:3857 metres, trying every pair
    of names as a hypothesis and keeping the one most names agree with. A block name ("SAKAE 3-CHOME") is printed
    on its block, near the point Nominatim returns: it agrees within tol_frac of the image diagonal and weighs
    (loose_frac / tol_frac)^2 in the fit. A district name is printed somewhere over its district, often far
    from its point (80 to 290 px on a z15 Nagoya map, 2026-11-04, against 2 px for block names): it agrees
    within loose_frac. Two or three names always fit some similarity, so at least min_inliers names, and
    min_fraction of them, must agree, and unless three of them are block names, min_loose_inliers: the wider
    tolerance lets unrelated names agree by chance more often (eight random names, 2026-11-04: 4 % passed at
    0.06, 14 % at 0.10 with four required). Otherwise this is a declared failure. With three or more agreeing
    block names, the final fit uses those only.

    Returns m_per_px (mercator metres per image pixel), rotation_deg, zoom (the coarsest web map zoom whose 256 px
    tiles are at least as fine as the map's pixels, so the reference never has less detail than the map; on
    2026-11-04 the estimate came out 7 to 11 % coarse on three Tokyo maps, and rounding put one at z14 for a z15
    map), and bbox: the image's footprint under the fit, widened by margin_frac of its
    size and by three median name residuals on each side, as a hint for the reference."""
    n = len(points)
    if n < min_inliers:
        return {"status": "failed", "reason": f"{n} located names (need {min_inliers})", "points": points}
    zs = [complex(p["col"], -p["row"]) for p in points]
    tol = [(tol_frac if CHOME_NAME.match(p["name"]) else loose_frac) * math.hypot(width, height) for p in points]
    wt = [1.0 / t ** 2 for t in tol]
    Zs = [complex(*lonlat_to_mercator(p["lon"], p["lat"])) for p in points]
    diag = math.hypot(width, height)
    best = None
    for i in range(n):
        for j in range(i + 1, n):
            if abs(zs[i] - zs[j]) < 1e-6:
                continue
            a, b = _fit([(zs[i], Zs[i]), (zs[j], Zs[j])])
            if abs(a) == 0:
                continue
            inl = [k for k in range(n) if abs((Zs[k] - b) / a - zs[k]) < tol[k]]
            score = (sum(1 for k in inl if tol[k] < loose_frac * diag), len(inl))  # block names first
            if best is None or score > best_score:
                best, best_score = inl, score
    for _ in range(3):  # refit on the agreeing names, then re-collect them
        if not best or len(best) < 2:
            break
        a, b = _fit([(zs[k], Zs[k]) for k in best], [wt[k] for k in best])
        best = [k for k in range(n) if abs((Zs[k] - b) / a - zs[k]) < tol[k]]
    best = best or []
    exact = [k for k in best if tol[k] < loose_frac * diag]
    need = min_inliers if len(exact) >= 3 else max(min_inliers, min_loose_inliers)
    if len(best) < need or len(best) < min_fraction * n:
        return {"status": "failed", "reason": f"{len(best)} of {n} names agree on one scale and rotation, "
                f"{len(exact)} of them block names (need {need} and {min_fraction:.0%})", "points": points}
    if len(exact) >= 3:  # enough block names to fix the similarity with redundancy: district names only count
        a, b = _fit([(zs[k], Zs[k]) for k in exact])
    else:
        a, b = _fit([(zs[k], Zs[k]) for k in best], [wt[k] for k in best])
    res = sorted(abs((Zs[k] - b) / a - zs[k]) for k in best)
    m_per_px = abs(a)
    zoom_f = math.log2(2 * ORIGIN / (256 * m_per_px))
    # widen by the names' scatter too: a Tokyo map (2026-11-04) with names 36 px off their points got a
    # rotation a few degrees off, and the 25% margin missed its corner by about 200 m
    extra = 3 * res[len(res) // 2]
    mx, my = margin_frac * width + extra, margin_frac * height + extra
    corners = [complex(c, -r) for c in (-mx, width + mx) for r in (-my, height + my)]
    ll = [mercator_to_lonlat((a * z + b).real, (a * z + b).imag) for z in corners]
    return {"status": "ok", "m_per_px": m_per_px, "rotation_deg": math.degrees(math.atan2(a.imag, a.real)),
            "zoom": int(math.ceil(zoom_f - 0.05)), "zoom_float": zoom_f, "inliers": len(best), "names": n,
            "support": sorted(points[k]["name"] for k in best), "median_residual_px": res[len(res) // 2],
            "points": [{**p, "residual_px": abs((Zs[k] - b) / a - zs[k])} for k, p in enumerate(points)],
            "bbox": [min(x for x, _ in ll), min(y for _, y in ll), max(x for x, _ in ll), max(y for _, y in ll)]}


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
    ap.add_argument("--words", default=None, help="keep the OCR words in this JSON file and reuse them if present")
    a = ap.parse_args()
    if a.words and Path(a.words).exists():
        words = json.loads(Path(a.words).read_text(encoding="utf-8"))
    else:
        words = ocr_words.read_words(a.image, a.langs, a.scale, angles=a.angles)
        if a.words:
            Path(a.words).write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    names = []
    for w in sorted(words, key=lambda w: -w["conf"]):
        n = clean_name(w["text"])
        if n and w["conf"] >= a.min_conf and n not in names:
            names.append(n)
    names = names[:a.max_names]
    client = nominatim.Client(a.cache)
    cands = {}
    for n in names:
        hits = lookup(client, n, a.countrycodes)
        if hits:
            cands[n] = merge_near([{"lon": float(h["lon"]), "lat": float(h["lat"]),
                                    "importance": float(h.get("importance") or 0),
                                    "display_name": h.get("display_name")} for h in hits])
    cands = drop_covered(cands)
    hint = cluster(cands, a.radius_km, a.min_support, a.margin_km, a.min_weight)
    if hint["status"] == "ok":
        import cv2
        h, w = cv2.imread(a.image, cv2.IMREAD_GRAYSCALE).shape
        hint["scale"] = scale_from_names(located_points(words, hint["matches"]), w, h)
    hint["ocr_words"] = len(words)
    hint["names"] = names
    hint["nominatim"] = {"base": client.base, "requests": client.requests, "cached": client.cached}
    Path(a.out).write_text(json.dumps(hint, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: hint.get(k) for k in ("status", "reason", "bbox", "support")}, ensure_ascii=False))
    sys.exit(0 if hint["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
