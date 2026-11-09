"""Benchmark coding agents (Codex, Gemini) at georeferencing, with and without the skills of this repository.

    python evals/agents/bench.py make                                   # tasks and their truths, from bench.json
    python evals/agents/bench.py run --agent codex --cond skills --task L1-okayama [--rep 1]
    python evals/agents/bench.py score > results.tsv

Run from the repository root. Work goes to tmp/agent-bench/ (tasks/<id>/{task,truth}, runs/<agent>/<cond>/<id>-r<rep>/).
The agent sees only its workdir (work/): the task image, a hint written for the agent (agent_hint), and, with the
skills, a git archive of the repository without evals/. The truth never enters it. The runners in this directory
mount only that workdir into a container with fixed CPU, memory and process limits and a time limit.

Outcomes: accurate (largest error over the image <= --accurate-pct of the image radius, as in run_matrix.py),
inaccurate, declared_failure, invalid_answer, no_answer, timeout (cut off with no answer); on the negative task
(a hint that points at the wrong place) correct_reject or false_accept. provider_error (the runner failed with no
answer) is not an outcome of the agent and is to be run again, not graded.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "tmp" / "agent-bench"
MODELS = {"codex": ["-m", "gpt-6-luna"], "gemini": []}  # gemini: the runner's default, gemini-3.8-flash-low
RUNNERS = {"codex": HERE / "run_codex_docker.sh", "gemini": HERE / "run_gemini_docker.sh"}


def agent_hint(task_hint, t, ref_style):
    """What the agent is told. The task image's own style is not named: the reference is ref_style."""
    base = {"image": "image.png", "width": task_hint["width"], "height": task_hint["height"],
            "reference_style": ref_style, "tile_size": 256}
    kind = t.get("hint")
    if kind == "bbox":
        return {**base, "bbox": task_hint["bbox"], "zoom": task_hint["zoom"]}
    if kind == "wrong-bbox":
        w, s, e, n = task_hint["bbox"]
        cx, cy = t["wrong_center"]
        hw, hh = (e - w) / 2, (n - s) / 2
        return {**base, "bbox": [cx - hw, cy - hh, cx + hw, cy + hh], "zoom": task_hint["zoom"]}
    if kind == "country":
        return {**base, "country": t["country"]}
    raise ValueError(f"unknown hint kind {kind!r}")


def hint_text(t):
    if t.get("type") == "pko":
        return "- Nothing else is known about it beyond what is printed on it."
    if t.get("type") == "doc":
        return (f"- The map shows a place in the country with ISO code {t['country']!r}; you are not told where or at "
                "what scale.")
    if t.get("hint") == "country":
        return f"- The map shows a place in the country with ISO code {t['country']!r}; you are not told where or at what scale."
    return ("- bbox in hint.json is a rough area (longitude and latitude, west south east north) around the map, with a "
            "margin; zoom is the web map zoom level of a similar scale.")


def fill_prompt(template, workdir, skills, minutes, hint_line):
    s = re.sub(r"\{\{#SKILLS\}\}\n?(.*?)\{\{/SKILLS\}\}\n?", (lambda m: m.group(1)) if skills else "", template, flags=re.S)
    return s.replace("{{WORKDIR}}", workdir).replace("{{MINUTES}}", str(minutes)).replace("{{HINT_TEXT}}", hint_line)


def prepare_workdir(repo, rev, dest, task_dir, t, ref_style, skills):
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty; refusing to write into it")
    dest.mkdir(parents=True, exist_ok=True)
    if skills:
        tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", rev], check=True,
                             capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(dest)], input=tar, check=True)
        shutil.rmtree(dest / "evals", ignore_errors=True)
    (dest / "task").mkdir()
    kind = t.get("type", "raster")
    if kind == "raster":
        shutil.copyfile(Path(task_dir) / "task" / "image.png", dest / "task" / "image.png")
        th = json.loads((Path(task_dir) / "task" / "hint.json").read_text(encoding="utf-8"))
        hint = agent_hint(th, t, ref_style)
    elif kind == "doc":
        shutil.copyfile(Path(task_dir) / "task" / "document.pdf", dest / "task" / "document.pdf")
        hint = {"document": "document.pdf", "country": t["country"], "dpi": t["dpi"], "page_px": t["page_px"],
                "reference_style": ref_style, "tile_size": 256}
    elif kind == "pko":
        shutil.copyfile(Path(task_dir) / "task" / "map.pdf", dest / "task" / "map.pdf")
        hint = {"document": "map.pdf"}
    else:
        raise ValueError(f"unknown task type {kind!r}")
    (dest / "task" / "hint.json").write_text(json.dumps(hint, indent=2), encoding="utf-8")
    leaks = [str(p) for p in dest.rglob("*") if p.name == "truth.json" or p.name == "evals"]
    if leaks:
        raise SystemExit(f"the workdir holds evaluation material: {leaks}")
    return dest


def outcome(answer, score, negative, exit_code, accurate_pct, provider_error=False):
    if not isinstance(answer, dict):
        if answer is not None:
            return "invalid_answer"
        if provider_error:
            return "provider_error"
        return "timeout" if exit_code == 124 else "no_answer"
    if answer.get("status") == "failed":
        return "correct_reject" if negative else "declared_failure"
    if not score or score.get("status") != "scored":
        return "invalid_answer"
    if negative:
        return "false_accept"
    return "accurate" if score["max_pct_radius"] <= accurate_pct else "inaccurate"


def doc_box(placement, dpi):
    """The map's rectangle (x0, y0, x1, y1) in pixels of the page drawn at dpi."""
    left, top, w, h = placement["map_pt"]
    k = dpi / 72.0
    return (left * k, top * k, (left + w) * k, (top + h) * k)


def doc_answer_in_box(answer, box):
    """An answer in page pixels, as an answer for the crop box: it is scored over the map only, not over the page."""
    x0, y0, x1, y1 = box
    return {**answer, "image": {"width": int(round(x1 - x0)), "height": int(round(y1 - y0))},
            "gcps": [{**g, "col": g["col"] - x0, "row": g["row"] - y0} for g in answer["gcps"]]}


def points_of(fc):
    out = []
    for f in fc.get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") == "Point":
            out.append(tuple(g["coordinates"][:2]))
        elif g.get("type") == "MultiPoint":
            out.extend(tuple(c[:2]) for c in g["coordinates"])
    return out


def match_points(pred, ref, radius_km):
    """Greedy one-to-one matching, nearest pairs first, within radius_km (great circle)."""
    import math

    def km(a, b):
        p1, p2 = math.radians(a[1]), math.radians(b[1])
        dl = math.radians(b[0] - a[0])
        h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))

    pairs = sorted((km(p, r), i, j) for i, p in enumerate(pred) for j, r in enumerate(ref))
    used_p, used_r, n = set(), set(), 0
    for d, i, j in pairs:
        if d > radius_km:
            break
        if i in used_p or j in used_r:
            continue
        used_p.add(i)
        used_r.add(j)
        n += 1
    return {"matched": n, "n_pred": len(pred), "n_ref": len(ref),
            "precision": n / len(pred) if pred else None, "recall": n / len(ref) if ref else None}


def pko_outcome(m, threshold):
    ok = m["precision"] is not None and m["precision"] >= threshold and (m["recall"] or 0) >= threshold
    return "accurate" if ok else "inaccurate"


PUBLIC_OSM = re.compile(r"https?://((?:[a-z]\.)?tile\.openstreetmap\.org|nominatim\.openstreetmap\.org|overpass-api\.de|"
                        r"overpass\.kumi\.systems|api\.openstreetmap\.org)/")


def public_osm_hits(text):
    """Public OSM servers in URLs of an agent's log; the prompt forbids them. Only URLs count: the prompt (which
    Codex echoes into its log) and the skills name the servers to say they are not to be called."""
    return sorted(set(PUBLIC_OSM.findall(text)))


def load_spec():
    return json.loads((HERE / "bench.json").read_text(encoding="utf-8"))


PKO_SRC = Path("/sata_hdd_24tb/can_not_publish/un/pko/deployments")
PKO_PUBLISHED = Path("/Workspaces/repos/__yuiseki/_hf_data/un-pko-deployments/data")
PDF_UVX = ["uvx", "--with", "numpy", "--with", "pillow", "--with", "opencv-python-headless", "--with",
           "pypdfium2==5.14.0", "python"]


def make_raster(spec, t, task_out, truth_out):
    W, H = spec["size"]
    cmd = PDF_UVX + [str(ROOT / "evals/scripts/make_task.py"), "--style", t["style"], "--center", *map(str, t["place"]),
                     "--zoom", str(t.get("zoom", spec["zoom"])), "--size", str(W), str(H), "--distortion", t["kind"],
                     "--strength", str(t["strength"]), "--seed", str(t["seed"]), "--cache", str(ROOT / "tmp/tiles"),
                     "--photometric", t.get("photometric", "none"), "--task-out", str(task_out), "--truth-out", str(truth_out)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT / "evals/scripts")


def make(spec):
    for t in spec["tasks"]:
        d = WORK / "tasks" / t["id"]
        if (d / "truth").exists() and any((d / "truth").iterdir()):
            continue
        kind = t.get("type", "raster")
        if kind == "raster":
            r = make_raster(spec, t, d / "task", d / "truth")
        elif kind == "doc":
            r = make_raster(spec, t, d / "base" / "task", d / "truth")
            if r.returncode == 0:
                r = subprocess.run(PDF_UVX + [str(ROOT / "evals/scripts/make_doc_task.py"), str(d / "base/task/image.png"),
                                              "--out", str(d / "doc"), "--seed", str(t["seed"]), "--dpi", str(t["dpi"])],
                                   capture_output=True, text=True, cwd=ROOT / "evals/scripts")
            if r.returncode == 0:
                (d / "task").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(d / "doc" / f"{t['document']}.pdf", d / "task" / "document.pdf")
                shutil.copyfile(d / "doc" / "placement.json", d / "truth" / "placement.json")
        elif kind == "pko":
            (d / "task").mkdir(parents=True, exist_ok=True)
            (d / "truth").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PKO_SRC / t["file"], d / "task" / "map.pdf")
            shutil.copyfile(PKO_PUBLISHED / t["published"], d / "truth" / "published.geojson")
            r = subprocess.CompletedProcess([], 0, "", "")
        print(t["id"], r.returncode, r.stderr.strip()[-300:], file=sys.stderr)


def run(spec, agent, cond, task_id, rep, minutes, rev):
    t = next(x for x in spec["tasks"] if x["id"] == task_id)
    d = WORK / "runs" / agent / cond / f"{task_id}-r{rep}"
    if (d / "meta.json").exists():
        raise SystemExit(f"{d} has already run")
    wd = prepare_workdir(ROOT, rev, d / "work", WORK / "tasks" / task_id, t, spec["ref_style"], cond == "skills")
    template = {"raster": "prompt.md", "doc": "prompt-doc.md", "pko": "prompt-pko.md"}[t.get("type", "raster")]
    prompt = fill_prompt((HERE / template).read_text(encoding="utf-8"), "/work", cond == "skills", minutes, hint_text(t))
    (d / "prompt.md").write_text(prompt, encoding="utf-8")
    cmd = [str(RUNNERS[agent]), "--prompt", str(d / "prompt.md"), str(wd), *MODELS[agent]]
    env = {**__import__("os").environ, "EVAL_MINUTES": str(minutes)}
    t0 = time.time()
    with open(d / "log.jsonl", "w") as log, open(d / "stderr.log", "w") as err:
        r = subprocess.run(cmd, stdout=log, stderr=err, env=env)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", rev], capture_output=True, text=True).stdout.strip()
    (d / "meta.json").write_text(json.dumps({"agent": agent, "cond": cond, "task": task_id, "rep": rep,
                                             "model": MODELS[agent] or ["gemini-3.8-flash-low"], "exit": r.returncode,
                                             "seconds": round(time.time() - t0), "minutes": minutes, "rev": commit},
                                            indent=2), encoding="utf-8")
    print(d, r.returncode, round(time.time() - t0))


def score_all(spec, accurate_pct):
    sys.path.insert(0, str(ROOT / "evals/scripts"))
    import score_task
    from make_doc_task import crop_truth
    tasks = {t["id"]: t for t in spec["tasks"]}
    cols = ["agent", "cond", "task", "rep", "outcome", "max_pct_radius", "median_m", "n_gcps", "exit", "seconds", "public_osm", "reason"]
    print("\t".join(cols))
    for m in sorted((WORK / "runs").glob("*/*/*/meta.json")):
        meta = json.loads(m.read_text())
        d, t = m.parent, tasks[meta["task"]]
        kind = t.get("type", "raster")
        tdir = WORK / "tasks" / meta["task"] / "truth"
        ap = d / "work" / ("answer.geojson" if kind == "pko" else "answer.json")
        answer, sc = None, None
        if ap.exists():
            try:
                answer = json.loads(ap.read_text())
            except ValueError:
                answer = "unreadable"
        if kind == "pko" and isinstance(answer, dict) and answer.get("type") == "FeatureCollection":
            ref = points_of(json.loads((tdir / "published.geojson").read_text()))
            sc = match_points(points_of(answer), ref, radius_km=t.get("radius_km", 2.0))
            sc = {**sc, "status": "matched", "max_pct_radius": "", "median_m": "",
                  "n_gcps": f"{sc['matched']}/{sc['n_pred']}/{sc['n_ref']}"}
        elif isinstance(answer, dict) and answer.get("status") == "ok":
            try:
                truth = json.loads((tdir / "truth.json").read_text())
                if kind == "doc":
                    pl = json.loads((tdir / "placement.json").read_text())
                    box = doc_box(pl, t["dpi"])
                    truth = crop_truth(truth, pl, box, t["dpi"])
                    answer = doc_answer_in_box(answer, box)
                sc = score_task.score(answer, truth)
            except Exception as e:  # a malformed answer is the agent's, not ours
                sc = {"status": "error", "error": repr(e)}
        perr = meta["exit"] not in (0, 124) and answer is None
        if sc and sc.get("status") == "matched":
            o = pko_outcome(sc, threshold=t.get("threshold", 0.8))
        else:
            o = outcome(answer, sc, t["level"] == "negative", meta["exit"], accurate_pct, provider_error=perr)
        reason = answer.get("reason", "") if isinstance(answer, dict) else ""
        logs = "".join(p.read_text(errors="replace") for p in (d / "log.jsonl", d / "stderr.log") if p.exists())
        row = [meta["agent"], meta["cond"], meta["task"], meta["rep"], o, (sc or {}).get("max_pct_radius", ""),
               (sc or {}).get("median_m", ""), (sc or {}).get("n_gcps", ""), meta["exit"], meta["seconds"],
               ",".join(public_osm_hits(logs)) or "-",
               str(reason).replace("\t", " ").replace("\n", " ")[:120]]
        print("\t".join(f"{v:.3g}" if isinstance(v, float) else str(v) for v in row))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("make")
    r = sub.add_parser("run")
    r.add_argument("--agent", choices=sorted(RUNNERS), required=True)
    r.add_argument("--cond", choices=["skills", "baseline"], required=True)
    r.add_argument("--task", required=True)
    r.add_argument("--rep", type=int, default=1)
    r.add_argument("--minutes", type=int, default=30)
    r.add_argument("--rev", default="HEAD")
    s = sub.add_parser("score")
    s.add_argument("--accurate-pct", type=float, default=1.0)
    a = ap.parse_args()
    spec = load_spec()
    if a.cmd == "make":
        make(spec)
    elif a.cmd == "run":
        run(spec, a.agent, a.cond, a.task, a.rep, a.minutes, a.rev)
    else:
        score_all(spec, a.accurate_pct)


if __name__ == "__main__":
    main()
