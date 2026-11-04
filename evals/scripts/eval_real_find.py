"""Finding maps in real documents: score map_candidates output against map extents drawn by eye.

    python scripts/eval_real_find.py --truth truth.json --cands 'tmp/commons/v3/{n}' --out real-find.tsv

truth.json: {"docs": {"00": {"maps": [{"page": 1, "bbox_pt": [x0, y0, x1, y1]}, ...]}, ...}} in PDF points from
the bottom left, as map_candidates writes bbox_pt. "maps": [] is a document with no map (any candidate is wrong);
"maps": null is not boxed and is left out. --cands is a folder pattern with {n}, holding candidates.json.

Drawn extents are coarse and a crop of part of a map is still usable, so a candidate is on a map when, on the
same page, at least PURITY of the candidate lies inside one map's box and it covers at least COVER of that box.
    rank    1-based position of the first candidate on a map (0 = none)
    rank_part  the same without COVER: the first candidate that is all map, however little of it (a crop of
            the map's core is still map, a chart or a photograph is not)
    n       number of candidates
    no_map  the document has no map
"""

import argparse
import json
from pathlib import Path

PURITY = 0.8
COVER = 0.25


def _area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _inter(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def hit(c, maps, cover=COVER):
    box = c.get("bbox_pt")
    if not box or not _area(box):
        return False
    for m in maps:
        if m["page"] != c.get("page"):
            continue
        i = _inter(box, m["bbox_pt"])
        if i / _area(box) >= PURITY and i / _area(m["bbox_pt"]) >= cover:
            return True
    return False


def score_doc(cands, maps):
    rank = next((k + 1 for k, c in enumerate(cands) if hit(c, maps)), 0)
    part = next((k + 1 for k, c in enumerate(cands) if hit(c, maps, cover=0.0)), 0)
    return {"rank": rank, "rank_part": part, "n": len(cands), "no_map": not maps}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--cands", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    docs = json.loads(Path(a.truth).read_text(encoding="utf-8"))["docs"]
    rows = []
    for n, t in sorted(docs.items()):
        if t.get("maps") is None:
            continue
        f = Path(a.cands.format(n=n)) / "candidates.json"
        cands = json.loads(f.read_text(encoding="utf-8"))["candidates"] if f.exists() else []
        rows.append({"doc": n, **score_doc(cands, t["maps"])})
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("doc\trank\trank_part\tn\tno_map\n")
        for r in rows:
            fh.write(f"{r['doc']}\t{r['rank']}\t{r['rank_part']}\t{r['n']}\t{int(r['no_map'])}\n")
    withmap = [r for r in rows if not r["no_map"]]
    print(json.dumps({"docs": len(withmap), "first": sum(r["rank"] == 1 for r in withmap),
                      "top3": sum(1 <= r["rank"] <= 3 for r in withmap),
                      "first_part": sum(r["rank_part"] == 1 for r in withmap), "none": sum(r["rank"] == 0 for r in withmap),
                      "no_map_docs": len(rows) - len(withmap)}))


if __name__ == "__main__":
    main()
