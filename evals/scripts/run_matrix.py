"""Run the tool-only pipeline over a grid of tasks and classify each outcome.

    python scripts/run_matrix.py matrix.json --work tmp/matrix --out results.tsv

matrix.json: {"level": 1, "zoom": 15, "registrars": ["feature-registration", "cross-style-registration"], "size": [900, 700], "ref_style": "osm-liberty", "photometrics": ["none", "gray"],
              "places": {"tokyo": [139.7528, 35.6852], ...}, "styles": ["osm-liberty"],
              "kinds": ["similarity", ...], "strengths": [0.25, ...], "seeds": [1, 2]}
ref_style is the style of the reference the solver matches against; styles are the task images' styles
(level 1 uses the same one, level 2 others).

Each task runs make_task -> fetch_reference -> register -> refine_gcps -> check_gcps -> score_task, each step a separate
process that writes a file; a step whose output exists is skipped, so an interrupted run resumes.
Outcomes (accurate means max error <= --accurate-pct of the image radius):
    ok              gates passed and accurate
    gate_hole       gates passed but inaccurate (the gates missed it)
    over_strict     gates failed but the answer was accurate
    refused         gates failed or the tool declared failure, and the answer was not accurate
Negative controls ("negatives": {"pairs": [[task_place, ref_place], ...], "kinds", "strengths", "seeds"}) make the
task at task_place but move the hint bbox, same size, to centre on ref_place; the reference is fetched and the gates
are run with that wrong hint. The right outcome is a refusal:
    correct_reject  the tool declared failure or a gate failed
    false_accept    every gate passed for a map of another place (a gate hole)
Every task gets exactly one row; a step that crashes is recorded as "error" with its stderr.
"""

import argparse
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
EVALS = Path(__file__).resolve().parent
UVX = ["uvx", "--with", "numpy", "--with", "pillow", "--with", "opencv-python-headless", "--with", "pyproj", "python"]
# one BLAS thread per step: many threads under a CPU quota fight each other (a 386-point gate check took
# over a minute with all threads and 11 s with one, 2026-11-03)
ENV = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
REGISTRARS = {"feature-registration": "register.py", "cross-style-registration": "register_cross_style.py"}
COLUMNS = ["id", "place", "style", "photometric", "kind", "strength", "seed", "outcome", "register", "gates_passed",
           "failed_gates", "max_m", "median_m", "max_pct_radius", "n_gcps", "n_removed", "registrar", "asift", "loo_max_px",
           "error"]


def tasks(m):
    for (place, lonlat), style, photo, kind, strength, seed in itertools.product(
            m["places"].items(), m["styles"], m.get("photometrics", ["none"]), m["kinds"], m["strengths"], m["seeds"]):
        tag = "" if photo == "none" else f"-{photo}"
        tid = f"L{m['level']}-{place}-{style}{tag}-{kind}-s{strength}-r{seed}"
        yield {"id": tid, "place": place, "center": lonlat, "style": style, "photometric": photo, "kind": kind,
               "strength": strength, "seed": seed}


def negatives(m):
    n = m.get("negatives")
    if not n:
        return
    for (tp, rp), kind, strength, seed in itertools.product(n["pairs"], n["kinds"], n["strengths"], n["seeds"]):
        yield {"id": f"N{m['level']}-{tp}-on-{rp}-{kind}-s{strength}-r{seed}", "place": tp, "center": m["places"][tp],
               "style": m["styles"][0], "photometric": "none", "kind": kind, "strength": strength, "seed": seed,
               "wrong_center": m["places"][rp]}


def shifted_bbox(bbox, center):
    w, s, e, n = bbox
    hw, hh = (e - w) / 2, (n - s) / 2
    return [center[0] - hw, center[1] - hh, center[0] + hw, center[1] + hh]


def classify(declared_failure, gates_passed, max_pct, accurate_pct):
    accurate = max_pct is not None and max_pct <= accurate_pct
    if gates_passed:
        return "ok" if accurate else "gate_hole"
    if accurate and not declared_failure:
        return "over_strict"
    return "refused"


def step(cmd, out, log):
    """Run cmd unless out exists. Exit 1 is a legitimate 'no' from register and check_gcps."""
    if Path(out).exists():
        return 0
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=ENV)
    Path(log).write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    if r.returncode not in (0, 1) or not Path(out).exists():
        raise RuntimeError(f"{' '.join(map(str, cmd[-6:]))} exited {r.returncode}: {r.stderr[-800:]}")
    return r.returncode


def run_one(t, m, work, cache, accurate_pct):
    d = Path(work) / t["id"]
    task, truth, run = d / "task", d / "truth", d / "run"
    for p in (task, truth, run):
        p.mkdir(parents=True, exist_ok=True)
    W, H = m["size"]
    step(UVX + [str(EVALS / "make_task.py"), "--style", t["style"], "--center", *map(str, t["center"]),
                "--zoom", str(m["zoom"]), "--size", str(W), str(H), "--distortion", t["kind"],
                "--strength", str(t["strength"]), "--seed", str(t["seed"]), "--cache", str(cache),
                "--task-out", str(task), "--truth-out", str(truth), "--photometric", t.get("photometric", "none")],
         truth / "truth.json", d / "make.log")
    hint = json.loads((task / "hint.json").read_text(encoding="utf-8"))
    hint_path = task / "hint.json"
    if "wrong_center" in t:
        hint = {**hint, "bbox": shifted_bbox(hint["bbox"], t["wrong_center"])}
        hint_path = run / "wrong_hint.json"
        hint_path.write_text(json.dumps(hint, indent=2), encoding="utf-8")
    step(UVX + [str(SKILLS / "tile-reference" / "scripts" / "fetch_reference.py"), "--style", m["ref_style"],
                "--zoom", str(hint["zoom"]), "--bbox", *map(str, hint["bbox"]), "--cache", str(cache),
                "--out", str(run / "ref")], run / "ref" / "reference.json", d / "fetch.log")
    # registrars in order: the first that does not declare failure gives the answer; every attempt is kept
    if not (run / "answer.json").exists():
        last = None
        for name in m.get("registrars", ["feature-registration"]):
            script = REGISTRARS[name]
            out = run / f"answer.{name}.json"
            code = step(UVX + [str(SKILLS / name / "scripts" / script), str(task / "image.png"), str(run / "ref"),
                               "--out", str(out)], out, d / f"register.{name}.log")
            last = out
            if json.loads(out.read_text(encoding="utf-8"))["status"] == "ok":
                break
        (run / "answer.json").write_text(last.read_text(encoding="utf-8"), encoding="utf-8")
    step(UVX + [str(SKILLS / "gcp-refinement" / "scripts" / "refine_gcps.py"), str(run / "answer.json"),
                "--out", str(run / "refined.json")], run / "refined.json", d / "refine.log")
    gates_out = run / "gates.json"
    if not gates_out.exists():
        r = subprocess.run(UVX + [str(SKILLS / "georef-gates" / "scripts" / "check_gcps.py"), str(run / "refined.json"),
                                  "--hint", str(hint_path)], capture_output=True, text=True, cwd=ROOT, env=ENV)
        if r.returncode not in (0, 1):
            raise RuntimeError(f"check_gcps exited {r.returncode}: {r.stderr[-800:]}")
        gates_out.write_text(r.stdout, encoding="utf-8")
    score_out = run / "score.json"
    if not score_out.exists():
        r = subprocess.run(UVX + [str(EVALS / "score_task.py"), str(run / "refined.json"), str(truth / "truth.json")],
                           capture_output=True, text=True, cwd=ROOT, env=ENV, check=True)
        score_out.write_text(r.stdout, encoding="utf-8")
    ans = json.loads((run / "refined.json").read_text(encoding="utf-8"))
    gates = json.loads(gates_out.read_text(encoding="utf-8"))
    sc = json.loads(score_out.read_text(encoding="utf-8"))
    loo = next((g.get("max_px") for g in gates["gates"] if g["name"] == "loo_residual"), None)
    pct = sc.get("max_pct_radius")
    if "wrong_center" in t:
        outcome = "false_accept" if gates["passed"] else "correct_reject"
    else:
        outcome = classify(gates["declared_failure"], gates["passed"], pct, accurate_pct)
    return {**{k: v for k, v in t.items() if k != "wrong_center"}, "outcome": outcome,
            "register": ans["status"], "gates_passed": gates["passed"],
            "failed_gates": ",".join(g["name"] for g in gates["gates"] if not g["passed"]),
            "max_m": sc.get("max_m"), "median_m": sc.get("median_m"), "max_pct_radius": pct,
            "n_gcps": len(ans["gcps"]), "n_removed": len(ans.get("refinement", {}).get("removed", [])),
            "registrar": ans.get("tool", {}).get("name"), "asift": ans.get("stats", {}).get("asift"),
            "loo_max_px": loo, "error": ""}


def fmt(v):
    if isinstance(v, float):
        return f"{v:.4g}"
    return "" if v is None else str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("matrix")
    ap.add_argument("--work", default="tmp/matrix")
    ap.add_argument("--cache", default="tmp/tiles")
    ap.add_argument("--out", required=True)
    ap.add_argument("--accurate-pct", type=float, default=1.0)
    a = ap.parse_args()
    m = json.loads(Path(a.matrix).read_text(encoding="utf-8"))
    all_tasks = list(tasks(m)) + list(negatives(m))
    rows = []
    for i, t in enumerate(all_tasks):
        try:
            row = run_one(t, m, a.work, a.cache, a.accurate_pct)
        except Exception as e:  # recorded, not hidden: one row per task
            row = {**t, "outcome": "error", "error": repr(e)[:300].replace("\t", " ").replace("\n", " ")}
        rows.append(row)
        print(f"[{i + 1}/{len(all_tasks)}] {t['id']} {row['outcome']} {fmt(row.get('max_m'))} m", flush=True)
    if len(rows) != len(all_tasks):
        raise RuntimeError("lost a task")
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(fmt(r.get(c)) for c in COLUMNS) + "\n")
    counts = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    print(json.dumps(counts))
    sys.exit(0)


if __name__ == "__main__":
    main()
