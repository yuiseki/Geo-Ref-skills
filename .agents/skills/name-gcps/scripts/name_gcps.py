"""Control points from the towns printed on a map: each town's symbol in the image, and its place in OpenStreetMap.

    python scripts/name_gcps.py image.png --out answer.json [--countrycodes xk,rs] [--cache tmp/nominatim]

For maps that do not look like the reference tiles (a thematic country map, such as the United Nations
peacekeeping maps), so image registration cannot match them, but whose towns are printed as a small ring
beside their name.

1. Read the words (tesseract, ocr_words.py) and keep those that look like place names (place_hint.clean_name),
   each at its most confident reading.
2. Look each name up on the self-hosted Nominatim. Keep exact name matches of class "place" (towns, villages)
   or administrative boundaries (a town linked to its municipality); a name usually has candidates in many
   places.
3. Find the similarity (scale, rotation within max_angle_deg, shift) from printed names to their places that the
   most names agree with, trying pairs of (name, candidate) at random. A name agrees when one of its
   candidates lies within tol_frac of the image diagonal of where the similarity puts it: a name is printed
   beside its town, not on it.
4. Find the ring symbols (template matching, outside every word read), and give each agreeing name the symbol
   beside its label that lies nearest to where the fit puts the town. Fit the transform (affine by default) to
   the symbols, drop the point farthest off until all lie within tol_px, and choose the symbols again from
   that fit.

Fewer than min_names agreeing names, or fewer than min_gcps control points left, is a declared failure
("status": "failed"). The answer has the same form as the registration tools' (check it with georef-gates).
"""

import argparse
import cmath
import json
import math
import random
import re
import sys
import unicodedata
from pathlib import Path

import cv2
import numpy as np

import place_hint as ph
import transforms as tf


SHORT_NAME = re.compile(r"^[A-Z][a-z]{2}$")


FOLD = str.maketrans({"đ": "d", "Đ": "D", "ð": "d", "Ð": "D", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ı": "i"})


def _ascii(t):
    """The letters without their diacritics (Štimlje: Stimlje), for judging whether a word looks like a name: the
    text layer of a PDF has them, and clean_name takes Latin letters only."""
    t = unicodedata.normalize("NFKD", t.translate(FOLD))
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _trimmed(w):
    """The name in a reading and the reading with its box narrowed to the name. tesseract reads the mark beside a
    town into the word ("\u2018Isiro", "{Juba", "\u00abKenge" on a Congo map, 2026-11-04); the characters that are
    not letters at either end are cut off, their share of the box with them."""
    t = w["text"]
    i, j = 0, len(t)
    while i < j and not t[i].isalpha():
        i += 1
    while j > i and not t[j - 1].isalpha():
        j -= 1
    core = t[i:j]
    a = _ascii(core)
    n = a if SHORT_NAME.match(a) else ph.clean_name(a)
    if n == a:  # judged on the letters without their marks, kept as printed: Nominatim finds Dračevo as such
        n = core
    if not n or (i == 0 and j == len(t)):
        return n, w
    cw = w["w"] / len(t)
    left = w["col"] - w["w"] / 2 + i * cw
    right = w["col"] + w["w"] / 2 - (len(t) - j) * cw
    return n, {**w, "text": core, "col": (left + right) / 2, "w": right - left}


def labels(words, min_conf=60.0):
    """{name: word} for words that look like place names, each at its most confident reading.

    Besides place_hint.clean_name (four letters or more), a three-letter word in title case: towns such as Wau,
    Bor and Yei are printed so on country maps (South Sudan, 2026-11-04). Such a name has candidates in many
    places, but only those that agree with the other names count."""
    out = {}
    for w in sorted(words, key=lambda w: -w["conf"]):
        if w["conf"] < min_conf:
            continue
        n, w = _trimmed(w)
        if n and n not in out:
            out[n] = w
    return out


def _ring(r, t=1.2, pad=3, dot=False):
    c = int(r + pad)
    yy, xx = np.mgrid[:2 * c + 1, :2 * c + 1]
    d = np.hypot(xx - c, yy - c)
    T = 255 * (1 - np.clip(1 - np.abs(d - r) / t, 0, 1))
    if dot:  # an administrative centre: a ring with a dot inside
        T[d <= 0.45 * r] = 0
    return T.astype(np.float32)


def _band(r0, r1, c):
    yy, xx = np.mgrid[:2 * c + 1, :2 * c + 1]
    d = np.hypot(xx - c, yy - c)
    K = ((d >= r0) & (d <= r1)).astype(np.float32)
    return K / K.sum()


def _disc(r, pad=3):
    c = int(r + pad)
    yy, xx = np.mgrid[:2 * c + 1, :2 * c + 1]
    d = np.hypot(xx - c, yy - c)
    return (255 * np.clip(d - r + 0.5, 0, 1)).astype(np.float32)


def ring_score(gray, radii=(3.0, 3.5, 4.0, 4.5, 5.0, 6.0), dot_radii=(4.0, 5.0, 6.0, 7.0, 8.0),
               disc_radii=(2.5, 3.0, 3.5, 4.0), min_contrast=40.0):
    """How much each pixel looks like the centre of a small dark ring (normalised cross-correlation, -1..1).

    The ring must be hollow: a band inside it (between the ring and the centre, or between the ring and the
    dot of an administrative centre) at least min_contrast grey levels lighter than the ring itself.
    Correlation alone scored a filled square 0.66, as high as a ring."""
    g = np.asarray(gray, np.float32)
    best = np.full(g.shape, -1.0, np.float32)
    for r, dot in [(r, False) for r in radii] + [(r, True) for r in dot_radii]:
        T = _ring(r, dot=dot)
        c = T.shape[0] // 2
        R = cv2.matchTemplate(g, T, cv2.TM_CCOEFF_NORMED)
        R = cv2.copyMakeBorder(R, c, c, c, c, cv2.BORDER_CONSTANT, value=-1)
        ring_mean = cv2.filter2D(g, -1, _band(r - 0.5, r + 0.5, c), borderType=cv2.BORDER_REPLICATE)
        lo, hi = (0.55 * r, 0.75 * r) if dot else (0.0, 0.5 * r)
        band_mean = cv2.filter2D(g, -1, _band(lo, hi, c), borderType=cv2.BORDER_REPLICATE)
        R[band_mean - ring_mean < min_contrast] = -1
        best = np.maximum(best, R)
    # a filled dot (a town, or a UN site, on the South Sudan map, 2026-11-04): its edge must be lighter than its
    # centre all round, so the inside of a larger filled shape does not count
    for r in disc_radii:
        T = _disc(r)
        c = T.shape[0] // 2
        R = cv2.matchTemplate(g, T, cv2.TM_CCOEFF_NORMED)
        R = cv2.copyMakeBorder(R, c, c, c, c, cv2.BORDER_CONSTANT, value=-1)
        inner = cv2.filter2D(g, -1, _band(0, 0.6 * r, c), borderType=cv2.BORDER_REPLICATE)
        outer = cv2.filter2D(g, -1, _band(r + 1.0, r + 2.0, c), borderType=cv2.BORDER_REPLICATE)
        R[outer - inner < min_contrast] = -1
        best = np.maximum(best, R)
    return best


RING_CHARS = set("oO0°@©®«»“”\"'")


def letter_boxes(words, min_conf=60.0, min_letters=3):
    """Boxes (col, row, w, h) of the letters of confident words: where a ring is a letter (o, e, a), not a town.

    tesseract reads a town's ring beside its name as part of the word ("Srbicao", "°Novi", 2026-11-04), so a
    ring-like character at either end is left out of the box when the word without it was read too, or when it
    is not a letter at all. Low-confidence readings (noise over roads and symbols) do not count."""
    texts = {w["text"].strip() for w in words if w["conf"] >= min_conf}
    out = []
    for w in words:
        t = w["text"].strip()
        if w["conf"] < min_conf or w.get("kind", "word") != "word" or sum(ch.isalpha() for ch in t) < min_letters:
            continue
        n = len(t)
        lead = 0
        while lead < n and (not t[lead].isalpha() or t[lead] in RING_CHARS and t[lead + 1:] in texts):
            lead += 1
        trail = 0
        while trail < n - lead and (not t[n - 1 - trail].isalpha()
                                    or t[n - 1 - trail] in RING_CHARS and t[:n - 1 - trail] in texts):
            trail += 1
        cw = w["w"] / n
        left = w["col"] - w["w"] / 2 + lead * cw
        right = w["col"] + w["w"] / 2 - trail * cw
        if right > left:
            out.append(((left + right) / 2, w["row"], right - left, w["h"]))
    return out


def symbol_peaks(score, words, min_score=0.4, window=7):
    """Local maxima of the ring score, except on the letters of words: o, e and a look like rings too."""
    boxes = letter_boxes(words)
    mx = cv2.dilate(score, np.ones((window, window), np.uint8))
    ys, xs = np.where((score >= min_score) & (score == mx))
    out = []
    for x, y in zip(xs, ys):
        if any(abs(x - c) <= bw / 2 + 1 and abs(y - r) <= bh / 2 + 1 for c, r, bw, bh in boxes):
            continue
        out.append({"col": x + _vertex(score, y, x, 1), "row": y + _vertex(score, y, x, 0), "score": float(score[y, x])})
    return out


def _vertex(s, y, x, axis):
    """Sub-pixel offset of a peak along one axis, from a parabola through it and its two neighbours: the
    integer peak alone is off by up to half a pixel, a sixth of the 3 px the gates allow."""
    H, W = s.shape
    if axis == 1 and 0 < x < W - 1:
        a, b, c = s[y, x - 1], s[y, x], s[y, x + 1]
    elif axis == 0 and 0 < y < H - 1:
        a, b, c = s[y - 1, x], s[y, x], s[y + 1, x]
    else:
        return 0.0
    d = a - 2 * b + c
    return float(np.clip(0.5 * (a - c) / d, -0.5, 0.5)) if d < 0 else 0.0


def fit_names(z, cands, diag, tol_frac=0.03, iters=60000, seed=0, max_angle_deg=30.0, min_pair_frac=0.1):
    """The similarity Z = a z + b (z = col - i row, Z mercator metres as x + i y) most names agree with.

    z: {name: complex}, cands: {name: [complex, ...]}. Returns a, b and {name: the agreeing candidate}."""
    names = [n for n in z if cands.get(n)]
    if len(names) < 2:
        return None, None, {}
    zs = np.array([z[n] for n in names])
    flat = np.array([q for n in names for q in cands[n]])
    owner = np.array([k for k, n in enumerate(names) for _ in cands[n]])
    starts = np.r_[0, np.cumsum([len(cands[n]) for n in names])[:-1]]
    pairs = [(k, q) for k, n in enumerate(names) for q in cands[n]]
    tol = tol_frac * diag
    rnd = random.Random(seed)

    def agree(a, b):
        d = np.abs(a * zs[owner] + b - flat) / abs(a)
        best = np.minimum.reduceat(d, starts)
        return best < tol, best

    best_key, best_ab = None, None
    for _ in range(iters):
        (k1, q1), (k2, q2) = rnd.sample(pairs, 2)
        dz = zs[k1] - zs[k2]
        if k1 == k2 or abs(dz) < min_pair_frac * diag:
            continue
        a = (q1 - q2) / dz
        if a == 0 or abs(math.degrees(cmath.phase(a))) > max_angle_deg:
            continue
        b = q1 - a * zs[k1]
        ok, d = agree(a, b)
        key = (int(ok.sum()), -float(d[ok].sum()))
        if best_key is None or key > best_key:
            best_key, best_ab = key, (a, b)
    if best_ab is None:
        return None, None, {}
    a, b = best_ab
    for _ in range(5):  # least squares over the agreeing names, then collect them again
        ok, _ = agree(a, b)
        idx = np.where(ok)[0]
        if len(idx) < 2:
            break
        P = a * zs[owner] + b
        chosen = {}
        for k in idx:
            sl = slice(starts[k], starts[k] + len(cands[names[k]]))
            chosen[k] = flat[sl][np.argmin(np.abs(P[sl] - flat[sl]))]
        src = np.array([zs[k] for k in idx])
        dst = np.array([chosen[k] for k in idx])
        ms, md = src.mean(), dst.mean()
        a = np.sum((dst - md) * np.conj(src - ms)) / np.sum(np.abs(src - ms) ** 2)
        b = md - a * ms
    ok, _ = agree(a, b)
    P = a * zs[owner] + b
    out = {}
    for k in np.where(ok)[0]:
        sl = slice(starts[k], starts[k] + len(cands[names[k]]))
        out[names[k]] = complex(flat[sl][np.argmin(np.abs(P[sl] - flat[sl]))])
    return complex(a), complex(b), out


def is_town_label(name):
    """Towns are printed in mixed case; names in capitals are countries, provinces and regions, which have no
    symbol (EQUATEUR, TSHUAPA and ANGOLA took a stray ring as their town, 2026-11-04)."""
    return not name.isupper()


def symbol_options(label, peaks, reach=1.2):
    """The symbols that may be a label's town: outside its box and within reach * its height of the box."""
    out = []
    for p in peaks:
        dx = max(abs(p["col"] - label["col"]) - label["w"] / 2, 0.0)
        dy = max(abs(p["row"] - label["row"]) - label["h"] / 2, 0.0)
        if (dx or dy) and math.hypot(dx, dy) <= reach * label["h"]:
            out.append(p)
    return out


def anchor(label, peaks, predicted, reach=1.2):
    """Of a label's symbol options, the one nearest to where the current fit puts the town; None if none."""
    opts = symbol_options(label, peaks, reach)
    if not opts:
        return None
    return min(opts, key=lambda p: math.hypot(p["col"] - predicted[0], p["row"] - predicted[1]))


def fit_symbols(options, places, diag, tol_px=8.0, iters=20000, seed=0, max_angle_deg=30.0, min_pair_frac=0.1):
    """The similarity Z = a s + b from symbols (s = col - i row) to places that the most names agree with,
    choosing one of each name's symbol options and one of its places. A label often has several ring-like marks
    within reach (an airport, a railway tick, the next town), and the label's own position predicts its town
    only to 20 to 40 px on a country map (Democratic Republic of the Congo, 2026-11-04), too loosely to choose
    among them. A name may also have several places near where the label says (Wau the town and Wau the
    county, South Sudan, 2026-11-04).

    options: {name: [complex, ...]}, places: {name: complex or [complex, ...]}.
    Returns a, b and {name: (the chosen symbol, the chosen place)}."""
    pl = {n: (list(v) if isinstance(v, (list, tuple)) else [v]) for n, v in places.items()}
    names = [n for n in options if options[n] and pl.get(n)]
    if len(names) < 2:
        return None, None, {}
    combos = {n: [(o, q) for o in options[n] for q in pl[n]] for n in names}
    S = np.array([o for n in names for o, _ in combos[n]])
    Z = np.array([q for n in names for _, q in combos[n]])
    starts = np.r_[0, np.cumsum([len(combos[n]) for n in names])[:-1]]
    rnd = random.Random(seed)

    def agree(a, b):
        d = np.abs(a * S + b - Z) / abs(a)
        best = np.minimum.reduceat(d, starts)
        return best < tol_px, best

    best_key, best_ab = None, None
    for _ in range(iters):
        k1, k2 = rnd.sample(range(len(names)), 2)
        (s1, q1), (s2, q2) = rnd.choice(combos[names[k1]]), rnd.choice(combos[names[k2]])
        ds = s1 - s2
        if abs(ds) < min_pair_frac * diag:
            continue
        a = (q1 - q2) / ds
        if a == 0 or abs(math.degrees(cmath.phase(a))) > max_angle_deg:
            continue
        b = q1 - a * s1
        ok, d = agree(a, b)
        key = (int(ok.sum()), -float(d[ok].sum()))
        if best_key is None or key > best_key:
            best_key, best_ab = key, (a, b)
    if best_ab is None:
        return None, None, {}
    a, b = best_ab
    ok, _ = agree(a, b)
    out = {}
    for k in np.where(ok)[0]:
        c = combos[names[k]]
        j = int(np.argmin([abs(a * o + b - q) for o, q in c]))
        out[names[k]] = (complex(c[j][0]), complex(c[j][1]))
    return complex(a), complex(b), out


def _gsd(model, src):
    c = src.mean(axis=0, keepdims=True)
    return float(np.sqrt(abs(np.linalg.det(model.jacobian(c)[0]))))


def robust_fit(pts, method="affine", tol_px=2.0):
    """Fit pixels (col, row) to mercator (x, y), dropping the point farthest off until every point lies within
    tol_px (in image pixels). Returns the kept points and the fit (None when too few are left)."""
    pts = list(pts)
    while len(pts) >= tf.MIN_POINTS[method] + 1:
        src = np.array([[p["col"], p["row"]] for p in pts], float)
        dst = np.array([[p["x"], p["y"]] for p in pts], float)
        try:
            m = tf.fit(method, src, dst)
        except ValueError:
            return pts, None
        res = np.hypot(*(m.predict(src) - dst).T) / _gsd(m, src)
        w = int(np.argmax(res))
        if res[w] <= tol_px:
            return pts, m
        pts = pts[:w] + pts[w + 1:]
    return pts, None


def one_per_symbol(pts, px=1.0):
    """One control point per symbol. Two names on one symbol are two readings of one label (Kumanovo and a
    misread Kumanove, 2026-11-04) or two names competing for it; counted twice, they would make the fit look
    better supported than it is. The first is kept."""
    out = []
    for p in pts:
        if all(math.hypot(p["col"] - q["col"], p["row"] - q["row"]) > px for q in out):
            out.append(p)
    return out


def merge_hits(hits, km=2.0):
    """Hits of one name within km of each other are one place. Its position is a town node's when there is one:
    a boundary's point may be its centre rather than the town's."""
    groups = []
    for h in hits:
        c = {"lon": float(h["lon"]), "lat": float(h["lat"]), "place": (h.get("category") or h.get("class")) == "place"}
        for g in groups:
            if ph.haversine_km(c["lon"], c["lat"], g[0]["lon"], g[0]["lat"]) <= km:
                g.append(c)
                break
        else:
            groups.append([c])
    out = []
    for g in groups:
        use = [c for c in g if c["place"]] or g
        out.append({"lon": sum(c["lon"] for c in use) / len(use), "lat": sum(c["lat"] for c in use) / len(use)})
    return out


def place_candidates(client, name, countrycodes=None):
    """Nominatim's exact matches of class place for a name, as mercator complex numbers (near ones merged)."""
    hits = ph.exact_hits(name, client.search(name, limit=40, countrycodes=countrycodes, namedetails=True))
    # towns come back as a place node or as the administrative boundary the node is linked to (Prokuplje,
    # Lipljan and Pristina only as the boundary, 2026-11-04); Nominatim puts a linked boundary at its town
    hits = [h for h in hits if (h.get("category") or h.get("class")) == "place"
            or ((h.get("category") or h.get("class")) == "boundary" and h.get("type") == "administrative")]
    merged = merge_hits(hits)
    return [complex(*ph.lonlat_to_mercator(c["lon"], c["lat"])) for c in merged]


def solve(gray, words, cands, method="affine", tol_frac=0.03, tol_px=2.0, min_names=6, min_gcps=12,
          max_angle_deg=30.0, iters=60000, seed=0, sym_tol_frac=0.005, extra_peaks=()):
    H, W = gray.shape
    diag = math.hypot(W, H)
    lab = labels(words)
    z = {n: complex(w["col"], -w["row"]) for n, w in lab.items() if cands.get(n)}
    a, b, agreeing = fit_names(z, {n: cands[n] for n in z}, diag, tol_frac, iters, seed, max_angle_deg)
    info = {"names_read": len(lab), "names_found": len(z), "names_agreeing": sorted(agreeing)}
    if len(agreeing) < min_names:
        return {"status": "failed", "reason": f"{len(agreeing)} names agree on one similarity (need {min_names})",
                **info}
    peaks = symbol_peaks(ring_score(gray), words)
    # symbols known exactly (a symbol font's characters in a PDF) replace any ring found within 2 px of them
    peaks = [p for p in peaks if all(math.hypot(p["col"] - q["col"], p["row"] - q["row"]) > 2 for q in extra_peaks)]
    peaks += [{"col": q["col"], "row": q["row"], "score": 1.0} for q in extra_peaks]
    options = {n: [complex(p["col"], -p["row"]) for p in symbol_options(lab[n], peaks)]
               for n in agreeing if is_town_label(n)}
    options = {n: o for n, o in options.items() if o}
    info["names_with_symbol"] = len(options)
    # every place of a name that the label fit allows, not only the nearest
    near = {n: [q for q in cands[n] if abs(a * z[n] + b - q) / abs(a) < tol_frac * diag] for n in options}
    sa, sb, chosen = fit_symbols(options, near, diag, sym_tol_frac * diag, iters // 3, seed, max_angle_deg)
    pts = [{"name": n, "col": s.real, "row": -s.imag, "x": q.real, "y": q.imag} for n, (s, q) in sorted(chosen.items())]
    kept, model = robust_fit(one_per_symbol(pts), method, tol_px)
    # choose each name's symbol and place again from the fit, now over every town name read, not only those the
    # label fit kept: on a country map the label fit misses names near the edges, where a non-linear projection
    # bends furthest from a similarity (Congo, 2026-11-04), and those are the names that fix the edges
    all_options = {n: [complex(p["col"], -p["row"]) for p in symbol_options(lab[n], peaks)] for n in z if is_town_label(n)}
    for _ in range(2):
        if model is None:
            break
        inv = tf.fit(method, np.array([[p["x"], p["y"]] for p in kept]), np.array([[p["col"], p["row"]] for p in kept]))
        pts = []
        for n in sorted(all_options):
            best = None
            for q in cands[n]:
                c, r = inv.predict([[q.real, q.imag]])[0]
                for o in all_options[n]:
                    d = abs(o - complex(c, -r))
                    if best is None or d < best[0]:
                        best = (d, o, q)
            if best is not None and best[0] <= sym_tol_frac * diag:
                _, o, q = best
                pts.append({"name": n, "col": o.real, "row": -o.imag, "x": q.real, "y": q.imag})
        kept, model = robust_fit(one_per_symbol(pts), method, tol_px)
    info["symbols_agreeing"] = len(chosen)
    if model is None or len(kept) < min_gcps:
        return {"status": "failed", "reason": f"{len(kept)} control points fit within {tol_px} px (need {min_gcps})",
                **info}
    gcps = []
    for p in kept:
        lon, lat = ph.mercator_to_lonlat(p["x"], p["y"])
        gcps.append({"col": p["col"], "row": p["row"], "lon": lon, "lat": lat, "name": p["name"]})
    return {"status": "ok", "method": method, "crs": "EPSG:4326", "gcps": gcps, **info}


def main():
    import nominatim
    import ocr_words

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--out", required=True)
    ap.add_argument("--langs", default="eng")
    ap.add_argument("--countrycodes", default=None)
    ap.add_argument("--cache", default="tmp/nominatim")
    ap.add_argument("--method", default="affine", choices=sorted(tf.MIN_POINTS))
    ap.add_argument("--tol-frac", type=float, default=0.03)
    ap.add_argument("--tol-px", type=float, default=2.0)
    ap.add_argument("--min-names", type=int, default=6)
    ap.add_argument("--min-gcps", type=int, default=12)
    ap.add_argument("--scales", type=float, nargs="+", default=[2.0, 3.0, 4.0, 5.0],
                    help="read the image enlarged by each factor; each finds names the others miss")
    ap.add_argument("--words", default=None, help="keep the OCR words in this JSON file and reuse them if present")
    ap.add_argument("--pdf", default=None, help="the PDF the image was rendered from: read its text layer instead of OCR")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=float, default=150.0, help="the dpi the image was rendered at from --pdf")
    ap.add_argument("--box-px", type=float, nargs=4, default=None,
                    help="where the image was cut from the page rendering, in its pixels (x0 y0 x1 y1)")
    ap.add_argument("--min-pdf-words", type=int, default=30,
                    help="fall back to OCR when the text layer has fewer words in the image (text drawn as outlines)")
    a = ap.parse_args()
    gray = cv2.imread(a.image, cv2.IMREAD_GRAYSCALE)
    H, W = gray.shape
    extra, source = [], "ocr"
    words = None
    if a.pdf:
        import pdf_words
        cs = pdf_words.chars(a.pdf, a.page)
        o = (a.box_px[0], a.box_px[1]) if a.box_px else (0, 0)
        inside = lambda w: 0 <= w["col"] <= W and 0 <= w["row"] <= H
        pw = [w for w in (pdf_words.to_pixels(x, a.dpi, o) for x in pdf_words.words(cs)) if inside(w)]
        mk = [m for m in (pdf_words.to_pixels({"text": m["ch"], "x": m["x"], "y": m["y"], "w": 0, "h": 0}, a.dpi, o)
                          for m in pdf_words.markers(cs)) if inside(m)]
        if sum(1 for w in pw if w["kind"] == "word") >= a.min_pdf_words:
            words, extra, source = pw, mk, "pdf"
    if words is not None:
        pass
    elif a.words and Path(a.words).exists():
        words = json.loads(Path(a.words).read_text(encoding="utf-8"))
    else:
        # one enlargement reads some names and misses others: on a Congo map (2026-11-04) 2, 3, 4 and 5 times
        # read 110 to 122 names each, 157 together
        words = [w for sc in a.scales for w in ocr_words.read_words(a.image, a.langs, sc, angles=[0.0])]
        if a.words:
            Path(a.words).write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    client = nominatim.Client(a.cache)
    cands = {n: place_candidates(client, n, a.countrycodes) for n in labels(words)}
    ans = solve(gray, words, cands, a.method, a.tol_frac, a.tol_px, a.min_names, a.min_gcps, extra_peaks=extra)
    ans = {"image": {"width": gray.shape[1], "height": gray.shape[0]},
           "tool": {"name": "name-gcps", "words_from": source, "symbols_from_pdf": len(extra), "langs": a.langs, "scales": a.scales, "tol_frac": a.tol_frac, "tol_px": a.tol_px},
           "nominatim": {"base": client.base, "requests": client.requests, "cached": client.cached}, **ans}
    Path(a.out).write_text(json.dumps(ans, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: ans.get(k) for k in ("status", "reason", "names_found")} | {"gcps": len(ans.get("gcps", []))}))
    sys.exit(0 if ans["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
