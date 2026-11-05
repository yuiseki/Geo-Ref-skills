"""Road access constraints maps as GeoJSON: every road drawn in a status colour, in longitude and latitude, one file
per map, for a time series.

    python scripts/road_geojson.py --results results.jsonl --runs runs --src pdfs --out geojson

Reads what the georeferencing batch left (deployment-batch: results.jsonl, and per PDF the candidates, answers and
gates), reads the roads from the PDF (road_access.py) and writes one GeoJSON per map that passed every gate.

- The geometry comes from the panel whose answer passed every gate (the map's frame). Points outside it, and points
  inside another rectangle found within it (an enlargement of one area at its own scale, the Koch inset of the
  versions of December 2025 to March 2026), are cut off. The blue box around Unity only marks what the inset
  enlarges; its lines are at the map's scale and are kept.
- status is the colour the line is drawn in. The road's number and its table row (ends, truck class, the table's
  status) are added only on maps whose labels and lines agree (labels_reliable): the numbered versions of December
  2025 to March 2026 put their labels in boxes away from the lines and disagree too often.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np

import pdf_words as pw
import road_access as ra
import transforms as tf
import webmercator as wm

HERE = Path(__file__).resolve().parent
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"])}
BASED_ON = "Based on United Nations World Food Programme (WFP) Logistics Cluster map"
DISCLAIMER = ("Derived automatically from a WFP Logistics Cluster map by software that uses no LLM or VLM. ABSOLUTELY NO "
              "WARRANTY: road positions, names and statuses may be wrong, and no accuracy is guaranteed. Not an official "
              "WFP or United Nations product and not endorsed by them. The source map displays the physical condition of "
              "the roads only, not security or political access.")
SHORT = "ABSOLUTELY NO WARRANTY: this road and its status may be wrong."


def date_of(name):
    """The map's date from its file name: YYYYMMDD, else 'D Month YYYY'."""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})[ -]([a-z]+)[ -](20\d{2})", name.lower())
    if m and m.group(2) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def geometry(parts, P, exclude):
    """Page-point polylines as a LineString or MultiLineString in longitude and latitude, through panel P; points
    outside the panel or inside one of the exclude boxes (rendering pixels, x0 y0 x1 y1) cut a line; pieces under 2
    points are dropped. [] if nothing is left."""
    out = []
    for part in parts:
        cur = []
        for x, y in part:
            px, py = x * P["k"], y * P["k"]
            c, r = px - P["o"][0], py - P["o"][1]
            keep = 0 <= c <= P["W"] and 0 <= r <= P["H"] and not any(b[0] <= px <= b[2] and b[1] <= py <= b[3] for b in exclude)
            if keep:
                cur.append((c, r))
            else:
                if len(cur) >= 2:
                    out.append(cur)
                cur = []
        if len(cur) >= 2:
            out.append(cur)
    if not out:
        return []
    lines = []
    for piece in out:
        m = P["model"].predict(np.array(piece, float))
        lines.append([[round(v, 5) for v in wm.mercator_to_lonlat(mx, my)] for mx, my in m])
    if len(lines) == 1:
        return [{"type": "LineString", "coordinates": lines[0]}]
    return [{"type": "MultiLineString", "coordinates": lines}]


def labels_reliable(lines, max_share=0.05):
    """Whether a map's road labels may be trusted: of its labelled lines, at most max_share disagree with the table."""
    lab = [x for x in lines if x["ids"]]
    return bool(lab) and sum(1 for x in lab if x["agrees"] is False) <= max_share * len(lab)


def panel_of(run, result):
    """The panel whose answer passed every gate, as geometry() takes it, and the boxes of the other frames inside it."""
    cands = json.loads((run / "cands/candidates.json").read_text())["candidates"]
    ci, meth = result["cand"], result["method"]
    cand = cands[ci - 1]
    if cand["from"].get("kind") != "rendered":
        return None, []
    ans = json.loads((run / f"answer.c{ci}.{meth}.json").read_text())
    src = np.array([[q["col"], q["row"]] for q in ans["gcps"]])
    dst = np.array([wm.lonlat_to_mercator(q["lon"], q["lat"]) for q in ans["gcps"]])
    box = cand["from"]["box_px"]
    P = {"k": cand["dpi"] / 72.0, "o": box[:2], "W": ans["image"]["width"], "H": ans["image"]["height"],
         "model": tf.fit(ans["method"], src, dst), "gcps": len(src), "method": ans["method"]}
    inner = []
    for i, c in enumerate(cands):
        b = c["from"].get("box_px")
        # every rectangle found on the same rendering inside the frame, a vector frame or not: the Koch inset of
        # January 2026 was found only on the rendered page
        if i == ci - 1 or c["from"].get("kind") != "rendered" or not b or c.get("dpi") != cand["dpi"]:
            continue
        if box[0] - 2 <= b[0] and box[1] - 2 <= b[1] and b[2] <= box[2] + 2 and b[3] <= box[3] + 2 and \
                (b[2] - b[0]) * (b[3] - b[1]) < 0.5 * (box[2] - box[0]) * (box[3] - box[1]):
            inner.append(b)
    return P, inner


def features(lines, rows, P, exclude, date, use_labels):
    by_id = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)
    fs = []
    for ln in lines:
        g = geometry(ln["parts"], P, exclude)
        if not g:
            continue
        p = {"date": date, "status": ln["status"], "colour": "#%02x%02x%02x" % tuple(ln["colour"])}
        if use_labels and ln["ids"]:
            rs = [r for i in dict.fromkeys(ln["ids"]) for r in by_id.get(i, [])]
            p.update({"road_ids": list(dict.fromkeys(ln["ids"])),
                      "roads": [{k: r[k] for k in ("road", "from", "via", "to", "truck", "status")} for r in rs],
                      "agrees_with_table": ln["agrees"]})
        p["no_warranty"] = SHORT
        fs.append({"type": "Feature", "geometry": g[0], "properties": p})
    return fs


def tool_commit(paths, repo):
    st = subprocess.run(["git", "status", "--porcelain", "--", *map(str, paths)], cwd=repo, capture_output=True, text=True).stdout
    if st.strip():
        raise RuntimeError("commit the tool first, its commit hash goes into the output:\n" + st)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def main():
    import pypdfium2 as pdfium
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    commit = tool_commit(sorted(HERE.glob("*.py")), HERE)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for line in open(a.results):
        res = json.loads(line)
        pdf = Path(a.src) / res["file"]
        date = date_of(res["file"])
        if res.get("stage") != "ok":
            summary.append({"date": date, "skip": "not georeferenced", "stage": res.get("stage")})
            continue
        P, inner = panel_of(Path(a.runs) / pdf.stem, res)
        if P is None:
            summary.append({"date": date, "skip": "the panel that passed is not a rendering of the page"})
            continue
        page = pdfium.PdfDocument(str(pdf))[0]
        ps = ra.paths(page)
        words = pw.words(pw.chars(pdf))
        rows = ra.table_rows(words, [p for p in ps if p["fill"]])
        lines = ra.link(ra.road_lines(ps), words, rows)
        use = labels_reliable(lines)
        fs = features(lines, rows, P, inner, date, use)
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        fc = {"type": "FeatureCollection", "based_on": BASED_ON, "disclaimer": DISCLAIMER, "map_date": date,
              "country": "South Sudan", "source_sha256": sha, "tool": "https://github.com/yuiseki/Geo-Ref-skills",
              "tool_commit": commit, "georeference": {"method": P["method"], "gcps": P["gcps"], "loo_max_px": res.get("loo")},
              "labels_used": use, "features": fs}
        name = f"SSD_roads_{date}_{sha[:12]}.geojson"
        (out / name).write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        s = {"date": date, "file": name, "lines": len(lines), "features": len(fs), "labels_used": use,
             "insets_cut": len(inner), "table_rows": len(rows)}
        summary.append(s)
        print(json.dumps(s), flush=True)
    (out / "summary.json").write_text(json.dumps(sorted(summary, key=lambda s: s["date"] or ""), indent=1))


if __name__ == "__main__":
    main()
