"""Level 5: find the map in a document, then georeference it with the level 4 pipeline, and score it.

    python scripts/run_doc_matrix.py matrix.json --work tmp/matrix/level5 --out results.tsv

matrix.json is a level 4 matrix plus "documents": ["scan", "embedded", "tiled", "paper"]. For each task: make_task, then
make_doc_task puts the map on an A4 page among body text and a chart, as a scanned page (scan.pdf, paper.pdf)
and with the map as its own image (embedded.pdf) or as strips (tiled.pdf). The document-maps skill gives the candidates:
    embedded  every image object (extract_images), largest first, each at its own dpi
    tiled     as embedded, with strips joined back first (stitch_images)
    scan      the one page image, then map-like rectangles on it (find_map_rectangles), in their rank order
    paper     as scan, the page on yellowish paper with noise and JPEG
Each candidate becomes a level 4 task (its crop, and the truth composed for that crop) and goes through
run_matrix.run_one. The next candidate is tried only when the previous one declared failure (place-hint found
no place or scale, or registration declared failure), never because the gates disliked an answer.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import run_matrix as rm

DOCS = rm.SKILLS / "document-maps" / "scripts"
PDF_UVX = ["uvx", "--with", "numpy", "--with", "pillow", "--with", "opencv-python-headless", "--with",
           "pypdfium2==5.14.0", "python"]


def embedded_candidates(man, min_px=64):
    out = []
    for im in man["images"]:
        if "bbox_pt" not in im or not im.get("px") or min(im["px"]) < min_px:
            continue
        x0, y0, x1, y1 = im["bbox_pt"]
        dpi = im["px"][0] * 72.0 / (x1 - x0)
        hpt = im["page_size_pt"][1]
        k = dpi / 72.0
        out.append({"file": im["file"], "dpi": dpi, "box": [x0 * k, (hpt - y1) * k, x1 * k, (hpt - y0) * k],
                    "area": im["px"][0] * im["px"][1]})
    return sorted(out, key=lambda c: -c["area"])


def image_candidates(man, min_px=64):
    """Stitched pictures (stitch_images) and image objects together, largest first; a stitched picture is
    larger than any of its strips, so it comes before them."""
    return embedded_candidates({"images": list(man.get("stitched", [])) + list(man["images"])}, min_px)


def page_candidates(cands, dpi, max_n=3):
    return [{"box": c["box"], "dpi": dpi, "score": c["score"]} for c in cands[:max_n]]


def try_next(row):
    if row.get("outcome") != "refused":
        return False
    return row.get("failed_gates") == "place_hint" or row.get("register") not in ("ok", None)


def run_doc(t, m, work, cache, accurate_pct, kind):
    import cv2
    from make_doc_task import crop_truth
    base = Path(work) / t["id"]
    rm.run_one_make(t, m, base, cache)
    truth = json.loads((base / "truth" / "truth.json").read_text(encoding="utf-8"))
    doc = base / "doc"
    if not (doc / "placement.json").exists():
        subprocess.run(PDF_UVX + [str(rm.EVALS / "make_doc_task.py"), str(base / "task" / "image.png"), "--out",
                                  str(doc), "--seed", str(t["seed"])], check=True, cwd=rm.ROOT)
    placement = json.loads((doc / "placement.json").read_text(encoding="utf-8"))
    ex = doc / f"extract-{kind}"
    if not (ex / "manifest.json").exists():
        subprocess.run(PDF_UVX + [str(DOCS / "extract_images.py"), str(doc / f"{kind}.pdf"), "--out", str(ex)],
                       check=True, cwd=rm.ROOT, capture_output=True)
        subprocess.run(PDF_UVX + [str(DOCS / "stitch_images.py"), str(ex / "manifest.json")],
                       check=True, cwd=rm.ROOT, capture_output=True)
    man = json.loads((ex / "manifest.json").read_text(encoding="utf-8"))
    cands = []
    if kind in ("embedded", "tiled"):
        for c in image_candidates(man):
            cands.append({**c, "image": ex / c["file"], "crop": None})
    else:
        page = embedded_candidates(man)[0]  # the scanned page
        fc = doc / "find"
        if not (fc / "candidates.json").exists():
            subprocess.run(PDF_UVX + [str(DOCS / "find_map_rectangles.py"), str(ex / page["file"]), "--out", str(fc)],
                           check=True, cwd=rm.ROOT, capture_output=True)
        found = json.loads((fc / "candidates.json").read_text(encoding="utf-8"))["candidates"]
        for c in page_candidates(found, page["dpi"]):
            cands.append({**c, "image": ex / page["file"], "crop": c["box"]})
    tried = []
    row = {**t, "outcome": "refused", "failed_gates": "no_candidate", "register": "not run"}
    for i, c in enumerate(cands[:3]):
        tid = f"{t['id']}/{kind}-c{i + 1}"
        d = Path(work) / tid
        (d / "task").mkdir(parents=True, exist_ok=True)
        (d / "truth").mkdir(parents=True, exist_ok=True)
        img = cv2.imread(str(c["image"]), cv2.IMREAD_COLOR)
        if c["crop"]:
            x0, y0, x1, y1 = map(int, c["crop"])
            img = img[y0:y1, x0:x1]
            box = [x0, y0, x1, y1]
        else:
            box = c["box"]
        cv2.imwrite(str(d / "task" / "image.png"), img)
        ct = crop_truth(truth, placement, box, c["dpi"])
        ct["width"], ct["height"] = img.shape[1], img.shape[0]
        (d / "truth" / "truth.json").write_text(json.dumps(ct), encoding="utf-8")
        (d / "task" / "hint.json").write_text("{}", encoding="utf-8")
        row = rm.run_one({**t, "id": tid}, m, work, cache, accurate_pct)
        tried.append(f"c{i + 1}:{row['outcome']}")
        if not try_next(row):
            break
    return {**row, "id": f"{t['id']}/{kind}", "error": (row.get("error") or "") + f" tried {' '.join(tried)}"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("matrix")
    ap.add_argument("--work", default="tmp/matrix/level5")
    ap.add_argument("--cache", default="tmp/tiles")
    ap.add_argument("--out", required=True)
    ap.add_argument("--accurate-pct", type=float, default=1.0)
    a = ap.parse_args()
    m = json.loads(Path(a.matrix).read_text(encoding="utf-8"))
    rows = []
    jobs = [(t, k) for t in rm.tasks(m) for k in m.get("documents", ["scan", "embedded"])]
    for i, (t, kind) in enumerate(jobs):
        try:
            row = run_doc(t, m, a.work, a.cache, a.accurate_pct, kind)
        except Exception as e:  # recorded, not hidden
            row = {**t, "id": f"{t['id']}/{kind}", "outcome": "error", "error": repr(e)[:300].replace("\n", " ")}
        rows.append(row)
        print(f"[{i + 1}/{len(jobs)}] {row['id']} {row['outcome']} {rm.fmt(row.get('max_m'))} m {row.get('error', '')[-60:]}",
              flush=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(rm.COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(rm.fmt(r.get(c)) for c in rm.COLUMNS).replace("\n", " ") + "\n")
    counts = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    print(json.dumps(counts))
    sys.exit(0)


if __name__ == "__main__":
    main()
