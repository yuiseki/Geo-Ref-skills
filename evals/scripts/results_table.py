"""Build the results table in README.md from the matrices' TSVs kept in evals/results/.

    python3 evals/scripts/results_table.py            # rewrite the table between the markers
    python3 evals/scripts/results_table.py --check    # exit 1 if README.md does not match the TSVs (CI)

evals/results/table.json lists the rows: level, task, and either "tsv" (one or more TSV names in evals/results/,
optionally "style" to keep one style and "negatives" to print a fixed text instead of the controls) or "cells" for
a row that no matrix holds (written by hand, said so in its text). The table was copied by hand before and fell a
week behind the runs (2026-11-11); a matrix result goes in evals/results/ and the table is rebuilt from it.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
START, END = "<!-- results:start -->", "<!-- results:end -->"
HEADER = "| レベル | 課題 | 正解 | 関門の穴 | 対照の拒否 |\n|---|---|---:|---:|---:|\n"


def rows_of(names, where):
    out = []
    for n in names:
        with open(Path(where) / n, encoding="utf-8") as fh:
            out += list(csv.DictReader(fh, delimiter="\t"))
    return out


def cells(spec, where=RESULTS):
    """Correct / tasks, gate holes, rejected / controls. Tasks are ids starting with L, controls with N."""
    rows = rows_of(spec["tsv"], where)
    pos = [r for r in rows if r["id"].startswith("L") and ("style" not in spec or r.get("style") == spec["style"])]
    neg = [r for r in rows if r["id"].startswith("N")]
    ok = sum(r["outcome"] == "ok" for r in pos)
    holes = sum(r["outcome"] == "gate_hole" for r in pos)
    if "negatives" in spec:
        rej = spec["negatives"]
    elif neg:
        rej = f"{sum(r['outcome'] == 'correct_reject' for r in neg)}/{len(neg)}"
    else:
        rej = "(対照なし)"
    return [f"{ok}/{len(pos)}", str(holes), rej]


def table(manifest, where=RESULTS):
    lines = [HEADER]
    for spec in manifest:
        c = spec["cells"] if "cells" in spec else cells(spec, where)
        lines.append("| " + " | ".join([str(spec["level"]), spec["task"]] + c) + " |\n")
    return "".join(lines)


def replace_block(doc, body):
    a, b = doc.index(START) + len(START), doc.index(END)
    return doc[:a] + "\n" + body + doc[b:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--readme", default=str(ROOT / "README.md"))
    a = ap.parse_args()
    manifest = json.loads((RESULTS / "table.json").read_text(encoding="utf-8"))
    doc = Path(a.readme).read_text(encoding="utf-8")
    new = replace_block(doc, table(manifest))
    if a.check:
        if new != doc:
            print("README.md's results table does not match evals/results/; run evals/scripts/results_table.py",
                  file=sys.stderr)
            sys.exit(1)
        print("results table matches")
        return
    Path(a.readme).write_text(new, encoding="utf-8")


if __name__ == "__main__":
    main()
