"""Score place-hint on finished tasks: does the hint bbox contain the true footprint?

    python scripts/eval_place_hint.py --out results.tsv tmp/matrix/level2a/L2-*-none-* ...

For each task directory (with task/image.png and truth/truth.json) runs the place-hint skill (written to
run/place_hint.json; an existing one is reused) and classifies:
    contains     ok and the bbox holds all four corners of the true footprint
    misplaced    ok but some corner is outside (a wrong or too small hint: the dangerous case)
    refused      the skill declared failure
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents" / "skills" / "place-hint" / "scripts" / "place_hint.py"
UVX = ["uvx", "--with", "numpy", "--with", "opencv-python-headless", "python"]


def classify(hint, footprint):
    if hint.get("status") != "ok":
        return "refused", None
    w, s, e, n = hint["bbox"]
    inside = all(w <= x <= e and s <= y <= n for x, y in footprint)
    cx = sum(x for x, _ in footprint) / len(footprint)
    cy = sum(y for _, y in footprint) / len(footprint)
    off = max(abs((w + e) / 2 - cx), abs((s + n) / 2 - cy))
    return ("contains" if inside else "misplaced"), off


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--countrycodes", default="jp")
    ap.add_argument("--cache", default="tmp/nominatim")
    a = ap.parse_args()
    rows = []
    for d in map(Path, a.tasks):
        out = d / "run" / "place_hint.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            r = subprocess.run(UVX + [str(SCRIPT), str(d / "task" / "image.png"), "--out", str(out),
                                      "--countrycodes", a.countrycodes, "--cache", a.cache],
                               capture_output=True, text=True, cwd=ROOT)
            if r.returncode not in (0, 1) or not out.exists():
                rows.append((d.name, "error", "", "", r.stderr[-200:].replace("\t", " ").replace("\n", " ")))
                print(d.name, "error", flush=True)
                continue
        hint = json.loads(out.read_text(encoding="utf-8"))
        truth = json.loads((d / "truth" / "truth.json").read_text(encoding="utf-8"))
        outcome, off = classify(hint, truth["footprint_lonlat"])
        size = "" if hint.get("status") != "ok" else f"{hint['bbox'][2] - hint['bbox'][0]:.3f}x{hint['bbox'][3] - hint['bbox'][1]:.3f}"
        rows.append((d.name, outcome, "" if off is None else f"{off:.4f}", size, ",".join(hint.get("support", []))))
        print(d.name, outcome, flush=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("id\toutcome\tcentre_off_deg\tbbox_deg\tsupport\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    counts = {}
    for r in rows:
        counts[r[1]] = counts.get(r[1], 0) + 1
    print(json.dumps(counts))
    sys.exit(0)


if __name__ == "__main__":
    main()
