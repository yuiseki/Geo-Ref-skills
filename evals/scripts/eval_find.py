"""Level 5, finding only: does document-maps hand on the map first? No georeferencing, no network.

    python scripts/eval_find.py --maps 'tmp/matrix/level*/*/task/image.png' --n 60 --seed 0 --work tmp/find --out find.tsv

Takes a uniform random sample of map images (task images of earlier levels), puts each on an A4 page with
make_doc_task (scan, paper, embedded, tiled), runs the document-maps tools as run_doc_matrix does, and scores
the candidate list against the placement:
    rank   1-based position of the first candidate whose box overlaps the map with IoU >= 0.9 (0 = none)
    iou    that candidate's IoU (or the best IoU over all candidates when none reaches 0.9)
    n      number of candidates
For embedded and tiled the candidate boxes are the image objects (stitched first), for scan and paper the
rectangles from find_map_rectangles on the one page image.
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

import extract_images  # noqa: E402
import find_map_rectangles  # noqa: E402
import make_doc_task  # noqa: E402
import run_doc_matrix  # noqa: E402
import stitch_images  # noqa: E402


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


def one(map_path, work, seed, dpi=150):
    pl = make_doc_task.make_documents(map_path, work / "doc", seed=seed, dpi=dpi)
    left, top, w, h = pl["map_pt"]
    rows = []
    for kind in ("scan", "paper", "embedded", "tiled"):
        ex = work / f"extract-{kind}"
        man = extract_images.extract(work / "doc" / f"{kind}.pdf", ex)
        man["stitched"] = stitch_images.stitch(man, ex)
        cands = run_doc_matrix.image_candidates(man)
        if kind in ("scan", "paper"):
            page = cands[0]
            k = page["dpi"] / 72.0
            img = cv2.imread(str(ex / page["file"]), cv2.IMREAD_COLOR)
            boxes = [c["box"] for c in find_map_rectangles.find(img)]
        else:
            k = dpi / 72.0
            boxes = [[v * dpi / c["dpi"] for v in c["box"]] for c in cands]
        truth = [left * k, top * k, (left + w) * k, (top + h) * k]
        r, v = score(boxes, truth)
        rows.append({"kind": kind, "rank": r, "iou": round(v, 3), "n": len(boxes)})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--work", default="tmp/find")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    paths = sorted(glob.glob(a.maps))
    rng = np.random.default_rng(a.seed)
    pick = [paths[i] for i in sorted(rng.choice(len(paths), size=min(a.n, len(paths)), replace=False))]
    out = []
    for i, p in enumerate(pick):
        name = "/".join(Path(p).parts[-4:-2])
        for r in one(p, Path(a.work) / f"{i:03d}", seed=a.seed * 1000 + i):
            out.append({"map": name, **r})
            print(f"{name}\t{r['kind']}\t{r['rank']}\t{r['iou']}\t{r['n']}", flush=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("map\tkind\trank\tiou\tn\n")
        for r in out:
            fh.write(f"{r['map']}\t{r['kind']}\t{r['rank']}\t{r['iou']}\t{r['n']}\n")
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
