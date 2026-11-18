"""Benchmark coding agents (Claude Code, Codex, Gemini, OpenCode, Qoder) at georeferencing, with and without the skills of this repository.

    python evals/agents/bench.py make                                   # tasks and their truths, from bench.json
    python evals/agents/bench.py run --agent codex --cond skills --task L1-okayama [--rep 1]
    python evals/agents/bench.py score > results.tsv
    python evals/agents/bench.py summary results.tsv                    # reps counted per agent, cond and task

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
import hashlib
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
# The model arguments given to each runner. gemini and opencode take the runner's default (EVAL_MODEL), recorded below.
MODELS = {"claude": ["--model", "claude-sonnet-5-5"], "codex": ["-m", "gpt-6-luna"], "gemini": [], "opencode": [],
          "qoder": ["--model", "Auto"]}
RUNNER_DEFAULT_MODEL = {"gemini": "gemini-3.8-flash-low", "opencode": "opencode/deepseek-v4.1-flash-free"}
RUNNERS = {a: HERE / f"run_{a}_docker.sh" for a in MODELS}
# The services the prompts send the agent to. They are checked before a run: an outage would otherwise be graded as
# the agent's failure (or, worse, teach the agent a wrong lesson about the task).
SERVICES = {"tiles": "https://tile.yuiseki.net/styles/osm-liberty/0/0/0.png",
            "geocoder": "https://nominatim.yuiseki.net/status"}
GOOD = {"accurate", "correct_reject"}


def http_status(url, timeout=20):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "geo-ref-skills-evals-preflight"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def preflight(services, fetch=http_status):
    """The services that do not answer 200, as 'name (url): status'. Empty when all answer."""
    bad = []
    for name, url in services.items():
        try:
            st = fetch(url)
        except Exception as e:  # any failure to reach it is a failure of the environment
            st = repr(e)
        if st != 200:
            bad.append(f"{name} ({url}): {st}")
    return bad


def docker_image_id(image):
    r = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def image_record(agent, env, inspect=docker_image_id):
    """The image a run used, by name and id: the name is rebuilt in place (the CLI versions move), the id is not."""
    image = env.get("EVAL_IMAGE") or f"geo-ref-skills-evals-{agent}"
    return {"image": image, "image_id": inspect(image)}


def catalogue_record(env):
    """The model catalogue a run was pinned to (run_opencode_docker.sh, EVAL_OPENCODE_MODELS), by its SHA-256."""
    c = env.get("EVAL_OPENCODE_MODELS")
    return {"model_catalogue_sha256": hashlib.sha256(Path(c).read_bytes()).hexdigest()} if c else {}


def summarize(rows):
    """One row per (agent, cond, task) over the reps: n graded runs, good ones (accurate or correct_reject), the
    outcomes, and provider errors (not graded). single marks n == 1: one run does not tell two conditions apart."""
    from collections import Counter, defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[(r["agent"], r["cond"], r["task"])].append(r["outcome"])
    out = []
    for (agent, cond, task), outs in sorted(groups.items()):
        graded = [o for o in outs if o != "provider_error"]
        c = Counter(graded)
        out.append({"agent": agent, "cond": cond, "task": task, "n": len(graded),
                    "good": sum(c[o] for o in GOOD), "outcomes": ",".join(f"{k}:{v}" for k, v in sorted(c.items())),
                    "provider_errors": len(outs) - len(graded), "single": len(graded) == 1})
    return out


def _events(path):
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            yield e


def usage(d, cli):
    """Tokens of one run from what its CLI logged: tok_in counts every input token,
    cache reads included (tok_cached is that part), tok_out includes reasoning.
    Qoder logs zero tokens and only its credits. Blank when nothing was logged."""
    tin = cached = out = calls = 0
    credits = ""
    if cli == "opencode":
        for e in _events(d / "log.jsonl"):
            if e.get("type") == "step_finish":
                t = e.get("part", {}).get("tokens", {})
                c = t.get("cache", {})
                tin += t.get("input", 0) + c.get("read", 0) + c.get("write", 0)
                cached += c.get("read", 0)
                out += t.get("output", 0) + t.get("reasoning", 0)
                calls += 1
    elif cli == "gemini":
        for e in _events(d / "log.jsonl"):
            st = e.get("step_update", {})
            u = st.get("usage")
            if e.get("event") == "step_update" and st.get("state") == "DONE" and u:
                tin += u.get("input_tokens", 0) + u.get("cache_read_tokens", 0)
                cached += u.get("cache_read_tokens", 0)
                out += u.get("output_tokens", 0) + u.get("thinking_tokens", 0)
                calls += 1
    elif cli == "codex":
        last = usage_of_rollout(d / "codex-session.jsonl")
        if last:  # input_tokens holds the cached ones, output_tokens the reasoning
            tin, cached, out, calls = last["input_tokens"], last["cached_input_tokens"], last["output_tokens"], ""
    elif cli in ("claude", "qoder"):
        for e in _events(d / "log.jsonl"):
            if e.get("type") == "result":
                u = e.get("usage", {})
                tin = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                cached, out, calls = u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0), e.get("num_turns", "")
                credits = e.get("total_credits", "")
    if not (tin or out):
        tin = cached = out = ""
        calls = calls or ""
    return {"tok_in": tin, "tok_cached": cached, "tok_out": out, "calls": calls, "credits": credits}


def codex_printed_total(stderr_text):
    """The total `codex exec` prints at the end: input - cached input + output."""
    m = re.search(r"tokens used\n([\d,]+)", stderr_text)
    return int(m.group(1).replace(",", "")) if m else None


def codex_session_index(sessions):
    """Codex's session files, by the total it printed for them."""
    index = {}
    for f in sorted(Path(sessions).rglob("*.jsonl")):
        u = usage_of_rollout(f)
        if u:
            index.setdefault(u["input_tokens"] - u["cached_input_tokens"] + u["output_tokens"], []).append(f)
    return index


def usage_of_rollout(f):
    last = None
    for e in _events(f):
        p = e.get("payload", {})
        if p.get("type") == "token_count" and p.get("info"):
            last = p["info"]["total_token_usage"]
    return last


CODEX_SESSION_END_SLACK_S = 600


def attach_codex_session(d, index):
    """Copy the session file of a Codex run into the run, matched by the total it printed.
    Codex writes it under its home, shared by every run, so the run itself has only the total."""
    if (d / "codex-session.jsonl").exists():
        return "present"
    err = d / "stderr.log"
    n = codex_printed_total(err.read_text(errors="replace")) if err.exists() else None
    if n is None:
        return "no total"
    found = index.get(n, [])
    if len(found) > 1:
        # Totals can repeat across days. The session's last write and the run's log both come as the run ends.
        ended = err.stat().st_mtime
        found = [f for f in found if abs(f.stat().st_mtime - ended) <= CODEX_SESSION_END_SLACK_S] or found
    if len(found) != 1:
        return "ambiguous" if found else "not found"
    shutil.copyfile(found[0], d / "codex-session.jsonl")
    return "attached"


def codex_sessions_dir(env):
    return Path(env.get("EVAL_CODEX_HOME") or Path(env.get("HOME", "~")).expanduser() / ".codex-evals") / "sessions"


def run_label(agent, env, variant=None):
    """Where a run is kept and how the score names it: the agent, with the model when EVAL_MODEL overrides the
    runner's default (so that runs of one agent with two models are not mixed), and +variant for runs of a
    changed setup (for example skills from another --rev) that must not be mixed with the plain ones."""
    if variant is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", variant):
        raise SystemExit(f"variant {variant!r}: lower-case letters, digits and hyphens only")
    m = env.get("EVAL_MODEL")
    label = agent if MODELS[agent] or not m or m == RUNNER_DEFAULT_MODEL[agent] else f"{agent}@{m.split('/')[-1]}"
    return f"{label}+{variant}" if variant else label


def cli_of(meta):
    """The CLI of a run: meta.json says it since run_label, older runs have only the plain agent name."""
    return meta.get("cli") or re.split(r"[@+]", meta["agent"])[0]


def model_record(agent, env):
    """The model a run used, for meta.json: the arguments given, or the runner's default (EVAL_MODEL overrides it)."""
    return MODELS[agent] or [env.get("EVAL_MODEL") or RUNNER_DEFAULT_MODEL[agent]]


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


def pdf_by_sha(src, sha, index):
    """The PDF under `src` whose SHA-256 is `sha`. The tasks name a PDF only by the hash the published file carries, since
    the UN file names hold the map reference numbers. Hashes are kept in `index` (rebuilt when a hash is not in it)."""
    idx = json.loads(index.read_text()) if index.exists() else {}
    if sha not in idx:
        idx = {hashlib.sha256(p.read_bytes()).hexdigest(): p.relative_to(src).as_posix() for p in sorted(src.rglob("*.pdf"))}
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps(idx, indent=0, sort_keys=True))
    if sha not in idx:
        raise SystemExit(f"no PDF under {src} has SHA-256 {sha}")
    return src / idx[sha]


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
            sha = json.loads((PKO_PUBLISHED / t["published"]).read_text())["source_sha256"]
            shutil.copyfile(pdf_by_sha(PKO_SRC, sha, WORK / "pdf-index.json"), d / "task" / "map.pdf")
            shutil.copyfile(PKO_PUBLISHED / t["published"], d / "truth" / "published.geojson")
            r = subprocess.CompletedProcess([], 0, "", "")
        print(t["id"], r.returncode, r.stderr.strip()[-300:], file=sys.stderr)


def run(spec, agent, cond, task_id, rep, minutes, rev, variant=None):
    t = next(x for x in spec["tasks"] if x["id"] == task_id)
    env = {**__import__("os").environ, "EVAL_MINUTES": str(minutes)}
    label = run_label(agent, env, variant)
    d = WORK / "runs" / label / cond / f"{task_id}-r{rep}"
    if (d / "meta.json").exists():
        raise SystemExit(f"{d} has already run")
    bad = preflight(SERVICES)
    if bad:  # nothing is written: the run is not the agent's to fail
        raise SystemExit("not started, a service the prompt names does not answer: " + "; ".join(bad))
    # the commit is fixed before the workdir is made from it: a commit made while the agent runs must not be recorded
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", rev], capture_output=True, text=True, check=True).stdout.strip()
    wd = prepare_workdir(ROOT, commit, d / "work", WORK / "tasks" / task_id, t, spec["ref_style"], cond == "skills")
    template = {"raster": "prompt.md", "doc": "prompt-doc.md", "pko": "prompt-pko.md"}[t.get("type", "raster")]
    prompt = fill_prompt((HERE / template).read_text(encoding="utf-8"), "/work", cond == "skills", minutes, hint_text(t))
    (d / "prompt.md").write_text(prompt, encoding="utf-8")
    cmd = [str(RUNNERS[agent]), "--prompt", str(d / "prompt.md"), str(wd), *MODELS[agent]]
    image = image_record(agent, env)
    t0 = time.time()
    with open(d / "log.jsonl", "w") as log, open(d / "stderr.log", "w") as err:
        r = subprocess.run(cmd, stdout=log, stderr=err, env=env)
    (d / "meta.json").write_text(json.dumps({"agent": label, "cli": agent, "variant": variant, "cond": cond, "task": task_id, "rep": rep,
                                             "model": model_record(agent, env), **image, **catalogue_record(env), "exit": r.returncode,
                                             "seconds": round(time.time() - t0), "minutes": minutes, "rev": commit},
                                            indent=2), encoding="utf-8")
    if agent == "codex":
        print("codex session:", attach_codex_session(d, codex_session_index(codex_sessions_dir(env))))
    print(d, r.returncode, round(time.time() - t0))


def score_all(spec, accurate_pct):
    sys.path.insert(0, str(ROOT / "evals/scripts"))
    import score_task
    from make_doc_task import crop_truth
    tasks = {t["id"]: t for t in spec["tasks"]}
    cols = ["agent", "cond", "task", "rep", "outcome", "max_pct_radius", "median_m", "n_gcps", "exit", "seconds", "public_osm",
            "tok_in", "tok_cached", "tok_out", "calls", "credits", "reason"]
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
               *usage(d, cli_of(meta)).values(),
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
    r.add_argument("--variant", help="keep these runs apart, as <agent>+<variant> (for example skills from another --rev)")
    s = sub.add_parser("score")
    s.add_argument("--accurate-pct", type=float, default=1.0)
    cs = sub.add_parser("codex-sessions", help="copy each Codex run's session file (its token counts) into the run")
    cs.add_argument("--sessions", help="default: $EVAL_CODEX_HOME/sessions, else ~/.codex-evals/sessions")
    sm = sub.add_parser("summary", help="read a score table (stdin) and count the reps of each agent, cond and task")
    sm.add_argument("table", nargs="?", default="-")
    a = ap.parse_args()
    spec = load_spec()
    if a.cmd == "make":
        make(spec)
    elif a.cmd == "run":
        run(spec, a.agent, a.cond, a.task, a.rep, a.minutes, a.rev, a.variant)
    elif a.cmd == "codex-sessions":
        import os
        index = codex_session_index(a.sessions or codex_sessions_dir(os.environ))
        for d in sorted((WORK / "runs").glob("codex*/*/*/")):
            print(d.relative_to(WORK), attach_codex_session(d, index))
    elif a.cmd == "summary":
        import csv
        f = sys.stdin if a.table == "-" else open(a.table, encoding="utf-8")
        rows = summarize(csv.DictReader(f, delimiter="\t"))
        cols = ["agent", "cond", "task", "n", "good", "outcomes", "provider_errors", "single"]
        print("\t".join(cols))
        for r in rows:
            print("\t".join(str(r[c]) for c in cols))
    else:
        score_all(spec, a.accurate_pct)


if __name__ == "__main__":
    main()
