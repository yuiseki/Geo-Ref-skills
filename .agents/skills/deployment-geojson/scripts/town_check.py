"""Check each deployment GeoJSON against the towns: the map's town symbols, placed by the map's own model, against the
places a self-hosted Nominatim gives for the names beside them. Keep the maps whose median distance is within a limit.

    python scripts/town_check.py --results work/results.jsonl --runs work/runs --src pdfs --geojson geojson --out checked \
        [--limit-km 10] [--nominatim-cache work/runs/nominatim-cache]

The gates check that the control points agree with one another, not that the map is where it says. A map can pass them
and still be off: MINUSMA 2023 put Bamako 52 km from its town symbol, and 61 of the maps of 2004-2019 had a median of
13 to 320 km (MONUSCO 2019: 144 to 320 km). Read the median, not the maximum: a name that is also another place
(Camp, Sahel) is tens or thousands of km off, and text in a sheet's corner (a table, a legend) is placed far away.

The limit was set from the maps, not in advance: in 2004-2019 no map lay between 9.8 and 13.4 km (2026-11-09).
A map with fewer than MIN_TOWNS towns measured is not passed: there is too little to say it is right.
Writes to --out each map that passes, with "checks": {"town": {...}} in its provenance, and town_check.jsonl with
every map's measurements (the worst names too). The files given are not changed.
"""
import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
for d in ("unit-symbols", "name-gcps", "deployment-batch"):
    sys.path.append(str(SKILLS / d / "scripts"))

import webmercator as wm  # noqa: E402

LIMIT_KM = 10.0
MIN_TOWNS = 3


def town_symbols(paths):
    """Centres of the small round paths (a town's dot or ring): curved, 1.5 to 7 pt, about as wide as high."""
    out = []
    for p in paths:
        w, h = p["box"][2] - p["box"][0], p["box"][3] - p["box"][1]
        if any(t == 1 for t, _, _ in p["segs"]) and 1.5 <= max(w, h) <= 7 and 0.7 <= (w + 1e-6) / (h + 1e-6) <= 1.4:
            out.append(((p["box"][0] + p["box"][2]) / 2, (p["box"][1] + p["box"][3]) / 2))
    return out


def labels(words):
    """The labels of a map: words and phrases (pdf_words) that no longer phrase holds. A word of a longer name ("Kafr"
    of "Kafr Shams" on UNDOF 2025) looked up alone is another place, far away."""
    def holds(a, b):  # a's text has b's as whole words and a's box covers b's centre
        return (a is not b and len(a["text"]) > len(b["text"]) and f" {b['text']} " in f" {a['text']} "
                and abs(b["x"] - a["x"]) <= a["w"] / 2 and abs(b["y"] - a["y"]) <= max(a.get("h", 0), b.get("h", 0)) / 2 + 1e-6)
    phrases = [w for w in words if w["kind"] == "phrase"]
    return [w for w in words if w["kind"] in ("word", "phrase") and not any(holds(p, w) for p in phrases)]


REACH = 1.2  # a town's symbol lies within this many label heights of the label's box (name-gcps's symbol_options)


def box_distance(q, w):
    """How far point q lies outside the word's box (0 inside it)."""
    dx = max(abs(q[0] - w["x"]) - w["w"] / 2, 0.0)
    dy = max(abs(q[1] - w["y"]) - w.get("h", 0) / 2, 0.0)
    return math.hypot(dx, dy), bool(dx or dy)


def pairs(words, symbols):
    """(name, symbol) for a capitalised word (not all capitals: a country beside a unit) with a town symbol beside it:
    outside its box (a round shape inside it is part of its lettering: on MINUSCA 2025 one was taken for every town
    and the median came out 30 km for a map right within 2 px) and within REACH label heights of the box (from the
    centre, a long name reached the ring of the town beside it). A symbol is the town of the nearest name only: a
    capital drawn with another symbol (Lubumbashi on MONUSCO 2025) otherwise takes the ring of its neighbour."""
    out = []
    for w in words:
        t = w["text"]
        if not t[:1].isupper() or t.isupper() or len(t) < 3 or any(ch.isdigit() for ch in t):
            continue
        near = [(d, q) for q in symbols for d, out_of_box in [box_distance(q, w)] if out_of_box and d <= REACH * w.get("h", 0)]
        if near:
            d, c = min(near)
            out.append((d, t, c))
    best = {}
    for d, t, c in out:
        if c not in best or d < best[c][0]:
            best[c] = (d, t)
    return [(t, c) for d, t, c in out if best[c] == (d, t)]


def distances(named, panels, places):
    """(km, name) per pair: the symbol through the model of the panel that would place a unit there (the smallest
    panel holding it, a local panel only near its control points: deployment_geojson.place), to the nearest place
    of that name (places(name): mercator complex numbers). A symbol no panel places is not measured: no unit there
    is placed either. Ground km: mercator metres times the cosine of the latitude."""
    import deployment_geojson as G
    out = []
    for name, (x, y) in named:
        P, c, r, _, reason = G.place(panels, x, y, need_std=False)
        if reason:
            continue
        cands = places(name)
        if not cands:
            continue
        X, Y = P["model"].predict([[c, r]])[0]
        q = min(cands, key=lambda q: abs(q - complex(X, Y)))
        _, lat = wm.mercator_to_lonlat(X, Y)
        out.append((abs(q - complex(X, Y)) * math.cos(math.radians(lat)) / 1000, name))
    return out


def extent_km(panels):
    """The ground length of the largest panel's diagonal (km), through its model: the scale a median is read against."""
    P = max(panels, key=lambda q: q["area"])
    (x0, y0), (x1, y1) = P["model"].predict([[0.0, 0.0], [float(P["W"]), float(P["H"])]])
    _, lat = wm.mercator_to_lonlat((x0 + x1) / 2, (y0 + y1) / 2)
    return math.hypot(x1 - x0, y1 - y0) * math.cos(math.radians(lat)) / 1000


def summarise(d):
    d = sorted(d)
    xs = [x for x, _ in d]
    if not xs:
        return {"n": 0, "median": None, "p25": None, "p75": None, "over10": 0, "worst": []}
    return {"n": len(xs), "median": round(statistics.median(xs), 2), "p25": round(xs[len(xs) // 4], 2),
            "p75": round(xs[3 * len(xs) // 4], 2), "over10": sum(x > 10 for x in xs),
            "worst": [[t, round(x, 1)] for x, t in d[-3:] if x > 10]}


def passes(s, limit_km=LIMIT_KM):
    return s["n"] >= MIN_TOWNS and s["median"] is not None and s["median"] <= limit_km


def with_town(fc, s, limit_km=LIMIT_KM):
    town = {"n": s["n"], "median_km": s["median"], "limit_km": limit_km, "passed": passes(s, limit_km)}
    checks = {**fc.get("checks", {}), "town": town}
    return {**{k: v for k, v in fc.items() if k != "features"}, "checks": checks, "features": fc["features"]}


def main():
    import pypdfium2 as pdfium
    import deployment_geojson as G
    import name_gcps as ng
    import nominatim as nm
    import pdf_words as pw
    import unit_symbols as us
    import batch
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--geojson", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit-km", type=float, default=LIMIT_KM)
    ap.add_argument("--nominatim-cache", default=None, help="default: <runs>/nominatim-cache")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cl = nm.Client(a.nominatim_cache or Path(a.runs) / "nominatim-cache")
    have = {}
    for p in Path(a.geojson).glob("*.geojson"):
        fc = json.loads(p.read_text())
        if fc["features"]:
            have[fc["source_sha256"]] = (p, fc)
    log = open(out / "town_check.jsonl", "w")
    for line in open(a.results):
        r = json.loads(line)
        pdf, run = Path(a.src) / r["file"], Path(a.runs) / Path(r["file"]).stem
        if r["stage"] not in ("ok", "failed") or not (run / "cands/candidates.json").exists():
            continue
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if sha not in have:
            continue
        p, fc = have.pop(sha)
        try:
            panels = G.panels_of(run, r["stage"] == "ok")
            syms = town_symbols(us.paths_of(pdfium.PdfDocument(str(pdf))[0]))
            words = labels(pw.words(pw.chars(pdf)))
            cc = batch.MISSIONS.get(r["mission"])
            s = summarise(distances(pairs(words, syms), panels, lambda n: ng.place_candidates(cl, n, cc)))
            s["extent_km"] = round(extent_km(panels), 1)
        except Exception as e:  # a failure is a failure: the map is not passed
            s = {**summarise([]), "error": repr(e)[:200]}
        ok = passes(s, a.limit_km)
        log.write(json.dumps({"file": p.name, "mission": r["mission"], **s, "passed": ok}, ensure_ascii=False) + "\n")
        log.flush()
        if ok:
            (out / p.name).write_text(json.dumps(with_town(fc, s, a.limit_km), ensure_ascii=False))
        print(p.name, s["n"], s["median"], "pass" if ok else "OUT", flush=True)


if __name__ == "__main__":
    main()
