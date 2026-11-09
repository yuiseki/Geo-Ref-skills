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
    shutil.copyfile(Path(task_dir) / "task" / "image.png", dest / "task" / "image.png")
    th = json.loads((Path(task_dir) / "task" / "hint.json").read_text(encoding="utf-8"))
    (dest / "task" / "hint.json").write_text(json.dumps(agent_hint(th, t, ref_style), indent=2), encoding="utf-8")
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


PUBLIC_OSM = re.compile(r"\b((?:[a-z]\.)?tile\.openstreetmap\.org|nominatim\.openstreetmap\.org|overpass-api\.de|"
                        r"overpass\.kumi\.systems|api\.openstreetmap\.org)")


def public_osm_hits(text):
    """Public OSM servers named in an agent's log; the prompt forbids them."""
    return sorted(set(PUBLIC_OSM.findall(text)))


def load_spec():
    return json.loads((HERE / "bench.json").read_text(encoding="utf-8"))


def make(spec):
    W, H = spec["size"]
    for t in spec["tasks"]:
        d = WORK / "tasks" / t["id"]
        if (d / "truth" / "truth.json").exists():
            continue
        cmd = ["uvx", "--with", "numpy", "--with", "pillow", "--with", "opencv-python-headless", "python",
               str(ROOT / "evals/scripts/make_task.py"), "--style", t["style"], "--center", *map(str, t["place"]),
               "--zoom", str(t.get("zoom", spec["zoom"])), "--size", str(W), str(H), "--distortion", t["kind"],
               "--strength", str(t["strength"]), "--seed", str(t["seed"]), "--cache", str(ROOT / "tmp/tiles"),
               "--photometric", t.get("photometric", "none"), "--task-out", str(d / "task"), "--truth-out", str(d / "truth")]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT / "evals/scripts")
        print(t["id"], r.returncode, r.stderr.strip()[-300:], file=sys.stderr)


def run(spec, agent, cond, task_id, rep, minutes, rev):
    t = next(x for x in spec["tasks"] if x["id"] == task_id)
    d = WORK / "runs" / agent / cond / f"{task_id}-r{rep}"
    if (d / "meta.json").exists():
        raise SystemExit(f"{d} has already run")
    wd = prepare_workdir(ROOT, rev, d / "work", WORK / "tasks" / task_id, t, spec["ref_style"], cond == "skills")
    prompt = fill_prompt((HERE / "prompt.md").read_text(encoding="utf-8"), "/work", cond == "skills", minutes, hint_text(t))
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
    tasks = {t["id"]: t for t in spec["tasks"]}
    cols = ["agent", "cond", "task", "rep", "outcome", "max_pct_radius", "median_m", "n_gcps", "exit", "seconds", "public_osm", "reason"]
    print("\t".join(cols))
    for m in sorted((WORK / "runs").glob("*/*/*/meta.json")):
        meta = json.loads(m.read_text())
        d, t = m.parent, tasks[meta["task"]]
        truth = json.loads((WORK / "tasks" / meta["task"] / "truth" / "truth.json").read_text())
        ap = d / "work" / "answer.json"
        answer, sc = None, None
        if ap.exists():
            try:
                answer = json.loads(ap.read_text())
            except ValueError:
                answer = "unreadable"
        if isinstance(answer, dict) and answer.get("status") == "ok":
            try:
                sc = score_task.score(answer, truth)
            except Exception as e:  # a malformed answer is the agent's, not ours
                sc = {"status": "error", "error": repr(e)}
        perr = meta["exit"] not in (0, 124) and answer is None
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
