"""Level 5, finding only: does document-maps hand on the map first? No georeferencing, no network.

    python scripts/eval_find.py --maps 'tmp/matrix/level*/*/task/image.png' --n 60 --seed 0 --work tmp/find --out find.tsv [--layout report]

Takes a uniform random sample of map images (task images of earlier levels), puts each on an A4 page with
make_doc_task (scan, paper, embedded, tiled), runs document-maps/map_candidates.py on each PDF, and scores the
candidate list (bbox_pt) against the placement:
    rank   1-based position of the first candidate whose box overlaps the map with IoU >= 0.9 (0 = none)
    iou    that candidate's IoU (or the best IoU over all candidates when none reaches 0.9)
    n      number of candidates
    via    the kind of the candidate that matched (image, stitched, rectangle, rendered)
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / ".agents/skills/document-maps/scripts"))

import make_doc_task  # noqa: E402
import map_candidates  # noqa: E402


def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / float(area(a) + area(b) - inter)


def score(boxes, truth):
    ious = [iou(b, truth) for b in boxes]
    for i, v in enumerate(ious):
        if v >= 0.9:
            return i + 1, v
    return 0, max(ious, default=0.0)


def one(map_path, work, seed, dpi=150, layout="plain"):
    pl = make_doc_task.make_documents(map_path, work / "doc", seed=seed, dpi=dpi, layout=layout)
    left, top, w, h = pl["map_pt"]
    H = pl["page_size_pt"][1]
    truth = [left, H - top - h, left + w, H - top]  # PDF points, origin bottom left, as bbox_pt
    rows = []
    for kind in ("scan", "paper", "embedded", "tiled"):
        res = map_candidates.collect(work / "doc" / f"{kind}.pdf", work / f"cands-{kind}", render_dpi=dpi)
        boxes = [c.get("bbox_pt", [0, 0, 0, 0]) for c in res["candidates"]]
        r, v = score(boxes, truth)
        first = res["candidates"][r - 1]["from"]["kind"] if r else ""
        rows.append({"kind": kind, "rank": r, "iou": round(v, 3), "n": len(boxes), "via": first})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--work", default="tmp/find")
    ap.add_argument("--out", required=True)
    ap.add_argument("--layout", default="plain", choices=["plain", "report"])
    a = ap.parse_args()
    paths = sorted(glob.glob(a.maps))
    rng = np.random.default_rng(a.seed)
    pick = [paths[i] for i in sorted(rng.choice(len(paths), size=min(a.n, len(paths)), replace=False))]
    out = []
    for i, p in enumerate(pick):
        name = "/".join(Path(p).parts[-4:-2])
        for r in one(p, Path(a.work) / f"{i:03d}", seed=a.seed * 1000 + i, layout=a.layout):
            out.append({"map": name, **r})
            print(f"{name}\t{r['kind']}\t{r['rank']}\t{r['iou']}\t{r['n']}\t{r['via']}", flush=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("map\tkind\trank\tiou\tn\tvia\n")
        for r in out:
            fh.write(f"{r['map']}\t{r['kind']}\t{r['rank']}\t{r['iou']}\t{r['n']}\t{r['via']}\n")
    summary = {}
    for r in out:
        s = summary.setdefault(r["kind"], {"first": 0, "top3": 0, "missed": 0, "all": 0})
        s["all"] += 1
        s["first"] += r["rank"] == 1
        s["top3"] += 1 <= r["rank"] <= 3
        s["missed"] += r["rank"] == 0
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
