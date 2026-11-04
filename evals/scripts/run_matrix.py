"""Run the tool-only pipeline over a grid of tasks and classify each outcome.

    python scripts/run_matrix.py matrix.json --work tmp/matrix --out results.tsv

matrix.json: {"level": 1, "zoom": 15, "registrars": ["feature-registration", "cross-style-registration"], "size": [900, 700], "ref_style": "osm-liberty", "photometrics": ["none", "gray"],
              "places": {"tokyo": [139.7528, 35.6852], ...}, "styles": ["osm-liberty"],
              "kinds": ["similarity", ...], "strengths": [0.25, ...], "seeds": [1, 2]}
ref_style is the style of the reference the solver matches against (ref_style_for: {task style: ref style}
overrides it per task style; registrar_args: {registrar: [extra arguments]}); styles are the task images' styles
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
Level 4 ("hint": "place-hint", optionally "zooms": [14, 15, 16] and "countrycodes": "jp") gives the solver no bbox
and no zoom: the place-hint skill reads the names on the map and fits their positions for the bbox and zoom. When it
cannot, the task is refused at that step (failed_gates "place_hint") and nothing else runs.
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
UVX = ["uvx", "--with", "numpy", "--with", "pillow", "--with", "opencv-python-headless", "--with", "pyproj",
       "--with", "scikit-image", "python"]
# one BLAS thread per step: many threads under a CPU quota fight each other (a 386-point gate check took
# over a minute with all threads and 11 s with one, 2026-11-03)
ENV = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
NOMINATIM_CACHE = ROOT / "tmp" / "nominatim"
REGISTRARS = {"feature-registration": "register.py", "cross-style-registration": "register_cross_style.py"}
COLUMNS = ["id", "place", "style", "photometric", "kind", "strength", "seed", "outcome", "register", "gates_passed",
           "failed_gates", "max_m", "median_m", "max_pct_radius", "n_gcps", "n_removed", "registrar", "asift", "loo_max_px",
           "error", "zoom"]


def tasks(m):
    zooms = m.get("zooms", [m.get("zoom")])
    for (place, lonlat), style, photo, zoom, kind, strength, seed in itertools.product(
            m["places"].items(), m["styles"], m.get("photometrics", ["none"]), zooms, m["kinds"], m["strengths"],
            m["seeds"]):
        tag = "" if photo == "none" else f"-{photo}"
        ztag = f"-z{zoom}" if "zooms" in m else ""  # ids without a zoom axis stay as they were (resumable runs)
        tid = f"L{m['level']}-{place}-{style}{tag}{ztag}-{kind}-s{strength}-r{seed}"
        yield {"id": tid, "place": place, "center": lonlat, "style": style, "photometric": photo, "zoom": zoom,
               "kind": kind, "strength": strength, "seed": seed}


def country_for(m, place):
    """The rough hint level 4 still gives: the country (ISO code), per place or for the whole matrix."""
    return m.get("countrycodes_for", {}).get(place, m.get("countrycodes", "jp"))


def hint_from_place_hint(ph):
    """Level 4 gives the solver no bbox and no zoom: both come from the place-hint skill (names read on the map,
    looked up, and fitted for scale). No agreeing names, or no scale, is a declared failure: None."""
    sc = ph.get("scale") or {}
    if ph.get("status") != "ok" or sc.get("status") != "ok":
        return None
    return {"bbox": sc["bbox"], "zoom": sc["zoom"], "zooms": sc.get("zooms", [sc["zoom"]]), "source": "place-hint"}


def attempts(m):
    """The registration attempts, in order. "attempts": [{"registrar", "ref_style"?, "args"?}, ...]; without it,
    "registrars" with "registrar_args". The next attempt runs only when the previous one declared failure; an
    answer that comes back is not swapped for another attempt's answer because the gates disliked it, since every
    extra try is another chance to pass the gates by luck."""
    if "attempts" in m:
        return m["attempts"]
    return [{"registrar": n, "args": m.get("registrar_args", {}).get(n, [])}
            for n in m.get("registrars", ["feature-registration"])]


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


def run_one_make(t, m, d, cache):
    """Make the task (image, hint, truth) in d unless its truth is already there."""
    task, truth = d / "task", d / "truth"
    for p in (task, truth, d / "run"):
        p.mkdir(parents=True, exist_ok=True)
    W, H = m["size"]
    step(UVX + [str(EVALS / "make_task.py"), "--style", t["style"], "--center", *map(str, t["center"]),
                "--zoom", str(t.get("zoom") or m["zoom"]), "--size", str(W), str(H), "--distortion", t["kind"],
                "--strength", str(t["strength"]), "--seed", str(t["seed"]), "--cache", str(cache),
                "--task-out", str(task), "--truth-out", str(truth), "--photometric", t.get("photometric", "none")],
         truth / "truth.json", d / "make.log")


def reference_refusal(err):
    """The reason when fetch_reference refused a reference too large to build (a wrong scale from the names asks
    for far more tiles than a map of this size can need): a declared failure, not an error. None otherwise."""
    import re
    hit = re.search(r"\d+ tiles needed, more than max_tiles=\d+", err)
    return hit.group(0) if hit else None


def run_one(t, m, work, cache, accurate_pct):
    d = Path(work) / t["id"]
    task, truth, run = d / "task", d / "truth", d / "run"
    run_one_make(t, m, d, cache)
    hint = json.loads((task / "hint.json").read_text(encoding="utf-8"))
    hint_path = task / "hint.json"
    if m.get("hint") == "place-hint":
        ph_out = run / "place_hint.json"
        step(UVX + [str(SKILLS / "place-hint" / "scripts" / "place_hint.py"), str(task / "image.png"), "--out",
                    str(ph_out), "--countrycodes", country_for(m, t["place"]), "--cache", str(NOMINATIM_CACHE)],
             ph_out, d / "place_hint.log")
        ph = json.loads(ph_out.read_text(encoding="utf-8"))
        hint = hint_from_place_hint(ph)
        if hint is None:
            why = (ph.get("scale") or {}).get("reason") or ph.get("reason")
            return {**t, "outcome": "refused", "register": "not run", "gates_passed": False,
                    "failed_gates": "place_hint", "error": f"place-hint: {why}"}
        hint_path = run / "hint.json"
        hint_path.write_text(json.dumps(hint, indent=2), encoding="utf-8")
    if "wrong_center" in t:
        hint = {**hint, "bbox": shifted_bbox(hint["bbox"], t["wrong_center"])}
        hint_path = run / "wrong_hint.json"
        hint_path.write_text(json.dumps(hint, indent=2), encoding="utf-8")
    ref_style = m.get("ref_style_for", {}).get(t["style"], m["ref_style"])

    def fetch(style, out, zoom):
        step(UVX + [str(SKILLS / "tile-reference" / "scripts" / "fetch_reference.py"), "--style", style,
                    "--zoom", str(zoom), "--bbox", *map(str, hint["bbox"]), "--cache", str(cache),
                    "--out", str(out)], out / "reference.json", d / f"fetch.{style}.log")

    # level 4 may offer a second zoom; it is tried only when every attempt at the first declared failure
    zooms = hint.get("zooms") or [hint["zoom"]]
    try:
        fetch(ref_style, run / "ref", zooms[0])
    except RuntimeError as e:
        why = reference_refusal(str(e))
        if why is None:
            raise
        return {**{k: v for k, v in t.items() if k != "wrong_center"}, "outcome": "refused", "register": "not run",
                "gates_passed": False, "failed_gates": "reference", "error": f"reference: {why}"}
    # registrars in order: the first that does not declare failure gives the answer; every attempt is kept
    if not (run / "answer.json").exists():
        last = None
        for zi, zoom in enumerate(zooms):
            zt = "" if zi == 0 else f"-z{zoom}"
            for att in attempts(m):
                name = att["registrar"]
                script = REGISTRARS[name]
                ref_dir = run / f"ref{zt}"
                tag = name
                if att.get("ref_style") and att["ref_style"] != ref_style:
                    ref_dir = run / f"ref-{att['ref_style']}{zt}"
                    tag = f"{name}.{att['ref_style']}"
                fetch(att.get("ref_style") or ref_style, ref_dir, zoom)
                if att.get("args"):
                    tag += "." + "-".join(a.strip("-") for a in att["args"])
                out = run / f"answer.{tag}{zt}.json"
                step(UVX + [str(SKILLS / name / "scripts" / script), str(task / "image.png"), str(ref_dir),
                            "--out", str(out)] + att.get("args", []), out, d / f"register.{tag}{zt}.log")
                last = out
                if json.loads(out.read_text(encoding="utf-8"))["status"] == "ok":
                    break
            else:
                continue
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
