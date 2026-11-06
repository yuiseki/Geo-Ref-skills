"""Level 6: a time-series-ready GeoJSON of unit deployments for every georeferenced peacekeeping map.

    python scripts/deployment_geojson.py --results results.jsonl --runs runs --src pdfs --out geojson

Reads what the batch left (one line per PDF in results.jsonl; per PDF, a run directory with the candidate list and,
per candidate and method, the answer and its gates), reads the units from the PDF (unit_symbols.py), and writes one
GeoJSON per map, named by mission, date and hash, in the form publish.py allows.

Which panels are used (a map's main frame, and the insets drawn as frames):
- a panel whose answer passed every gate, on a map that passed: every unit placed in it is used;
- a panel that failed only on how far its points spread (an inset whose space the unit boxes take; a map whose towns
  sit in one part of it) is used locally: a unit is kept only if its point lies among the panel's control points and
  its own leave-one-out spread is within 3 px. The jackknife alone does not see a model bend away from where it was
  fitted (a map with every control point west of 2.5 W put units 13 to 18 km off at 1.2 px of spread), hence the hull;
- a panel that failed on anything else is not used.
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

import pdf_words as pw
import publish
import transforms as tf
import webmercator as wm

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
LOCAL_STD_PX = 3.0
# a unit at a town whose name is a control point sits on the town's dot, a pixel or two from the point read there;
# on an inset whose towns lie along one road (MONUSCO 2025) that is outside the hull, by 0.2 to 1.9 px
HULL_TOL_PX = 3.0


def panel_use(failed, map_ok):
    """'global' (every point), 'local' (a point only if it passes the local checks) or None."""
    if set(failed) - {"spread", "edge_uncertainty"}:
        return None
    return "global" if map_ok and not failed else "local"


def inside_hull(src, c, r, tol=0.0):
    """Whether (c, r) lies in the convex hull of the control points (monotone chain, edges included), or within tol
    pixels of it."""
    pts = sorted(map(tuple, np.asarray(src, float)))

    def half(ps):
        h = []
        for p in ps:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h[:-1]

    hull = half(pts) + half(pts[::-1])
    if len(hull) < 3:
        return False
    edges = list(zip(hull, hull[1:] + hull[:1]))
    if all((x1 - x0) * (r - y0) - (y1 - y0) * (c - x0) >= 0 for (x0, y0), (x1, y1) in edges):
        return True

    def seg(x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((c - x0) * dx + (r - y0) * dy) / (dx * dx + dy * dy)))
        return math.hypot(c - x0 - t * dx, r - y0 - t * dy)
    # outside a convex polygon, the distance to it is the distance to its nearest edge
    return min(seg(x0, y0, x1, y1) for (x0, y0), (x1, y1) in edges) <= tol


def point_std(P, c, r):
    """How much the point moves when each control point in turn is left out (jackknife), in image pixels."""
    src, dst = P["src"], P["dst"]
    preds = []
    for i in range(len(src)):
        keep = np.arange(len(src)) != i
        try:
            preds.append(tf.fit(P["method"], src[keep], dst[keep]).predict([[c, r]])[0])
        except ValueError:
            return float("inf")
    preds = np.array(preds)
    n = len(preds)
    var = (n - 1) / n * ((preds - preds.mean(axis=0)) ** 2).sum(axis=1).sum()
    J = P["model"].jacobian(np.array([[c, r]]))[0]
    return float(math.sqrt(var) / math.sqrt(abs(np.linalg.det(J))))


def nearest_text(words, x, y, r=25):
    """The capitalised word nearest the point, within r pt. A hint, not a place name: it can be any label."""
    best = None
    for w in words:
        if w["kind"] != "word" or not w["text"][:1].isupper() or len(w["text"]) < 3:
            continue
        d = math.hypot(w["x"] - x, w["y"] - y) - w["w"] / 2
        if d < r and (best is None or d < best[0]):
            best = (d, w["text"])
    return best[1] if best else None


def panels_of(run, map_ok):
    cands = json.loads((run / "cands/candidates.json").read_text())["candidates"]
    panels = []  # every candidate panel whose answer may be used: the main map and its insets
    # a candidate may have several answers (town names, then the graticule: UNDOF 2025); one that passed every gate
    # comes first, then the others in name order
    def rank(g):
        failed = [x for x in json.loads(g.read_text())["gates"] if not x["passed"]]
        return (bool(failed), g.name)
    for g in sorted(run.glob("gates.c*.json"), key=rank):
        m = re.match(r"gates\.c(\d+)\.(\w+)\.json", g.name)
        if not m:
            continue
        failed = {x["name"] for x in json.loads(g.read_text())["gates"] if not x["passed"]}
        use = panel_use(failed, map_ok)
        ci, meth = int(m.group(1)), m.group(2)
        cand = cands[ci - 1]
        if use is None or cand["from"].get("kind") != "rendered" or any(p["cand"] == ci for p in panels):
            continue
        ans = json.loads((run / f"answer.c{ci}.{meth}.json").read_text())
        src = np.array([[q["col"], q["row"]] for q in ans["gcps"]])
        dst = np.array([wm.lonlat_to_mercator(q["lon"], q["lat"]) for q in ans["gcps"]])
        panels.append({"cand": ci, "local": use == "local", "src": src, "dst": dst, "method": ans["method"],
                       "k": cand["dpi"] / 72.0, "o": cand["from"]["box_px"][:2], "W": ans["image"]["width"],
                       "H": ans["image"]["height"], "model": tf.fit(ans["method"], src, dst),
                       "area": ans["image"]["width"] * ans["image"]["height"]})
    panels.sort(key=lambda p: p["area"])  # the smallest panel holding a point is the most detailed (an inset)
    return panels


def features_of(units, panels, words, mission, date, map_ok):
    feats, n_units, why = [], 0, {"no_location": 0, "outside_panels": 0, "outside_hull": 0, "uncertain": 0}
    for s in units["stacks"]:
        n = len(s["units"])
        n_units += n
        loc = s["location"]
        if not loc:
            why["no_location"] += n
            continue
        P = None
        for p in panels:
            c, r = loc["x"] * p["k"] - p["o"][0], loc["y"] * p["k"] - p["o"][1]
            if 0 <= c <= p["W"] and 0 <= r <= p["H"]:
                P = p
                break
        if P is None:
            why["outside_panels"] += n
            continue
        if P["local"] and not inside_hull(P["src"], c, r, tol=HULL_TOL_PX):
            why["outside_hull"] += n
            continue
        std = point_std(P, c, r)
        if P["local"] and std > LOCAL_STD_PX:
            why["uncertain"] += n
            continue
        lon, lat = wm.mercator_to_lonlat(*P["model"].predict([[c, r]])[0])
        text = nearest_text(words, loc["x"], loc["y"])
        for u in s["units"]:
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                          "properties": {"mission": mission, "date": date, "label": u["label"], "inner": u["inner"],
                                         "symbol": u["signature"], "arm": u.get("arm"), "echelon": u.get("echelon"),
                                         "size_marks": u.get("size_marks"), "nearest_text": text, "stack": s["stack"],
                                         "located_by": s["located_by"], "panel": P["cand"], "panel_local": P["local"],
                                         "map_ok": map_ok, "std_px": round(std, 2)}})
    return feats, n_units, why


def units_of(pdf, run, script):
    out = run / "units.json"
    if not out.exists() or out.stat().st_mtime < Path(script).stat().st_mtime:
        subprocess.run([sys.executable, str(script), str(pdf), "--out", str(out)], check=True, capture_output=True)
    return json.loads(out.read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--src", required=True, help="the directory of the PDFs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--units-script", default=str(SKILLS / "unit-symbols/scripts/unit_symbols.py"))
    ap.add_argument("--tool-commit", default=None, help="default: the HEAD of the repository, which must hold the tool unchanged")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    commit = a.tool_commit or publish.tool_commit(
        [SKILLS / n for n in ("deployment-batch", "unit-symbols", "deployment-geojson")], SKILLS)
    seen, summary = set(), open(out / "summary.jsonl", "w")
    for line in open(a.results):
        r = json.loads(line)
        run = Path(a.runs) / Path(r["file"]).stem
        if r["stage"] not in ("ok", "failed") or not (run / "cands/candidates.json").exists():
            continue
        pdf = Path(a.src) / r["file"]
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if sha in seen:  # the same PDF twice
            continue
        seen.add(sha)
        panels = panels_of(run, r["stage"] == "ok")
        if not panels:
            continue
        feats, n_units, why = features_of(units_of(pdf, run, a.units_script), panels, pw.words(pw.chars(pdf)),
                                          r["mission"], r["date"], r["stage"] == "ok")
        refs = publish.reference_numbers(Path(r["file"]).stem, r.get("title"))
        fc = publish.publishable(feats, sha, commit, r["date"], r["mission"], refs)
        name = publish.out_name(r["mission"], r["date"], sha)
        (out / name).write_text(json.dumps(fc, ensure_ascii=False))
        summary.write(json.dumps({"file": name, "mission": r["mission"], "date": r["date"], "map_ok": r["stage"] == "ok",
                                  "units": n_units, "located": len(feats), "panels": [p["cand"] for p in panels], **why}) + "\n")
        summary.flush()
        print(name, n_units, len(feats), why, flush=True)


if __name__ == "__main__":
    main()
