# uvx --with pytest --with numpy --with pyproj python -m pytest agents/test_bench.py
import json
import subprocess
from pathlib import Path

import pytest

import bench

ROOT = Path(__file__).resolve().parents[2]
TASK_HINT = {"image": "image.png", "width": 900, "height": 700, "bbox": [139.0, 35.0, 139.1, 35.1], "zoom": 15,
             "tile_size": 256, "style": "osm-bright", "tile_base": "https://tile.yuiseki.net/styles"}


def test_bbox_hint_names_the_reference_style_not_the_task_style():
    h = bench.agent_hint(TASK_HINT, {"hint": "bbox"}, "osm-liberty")
    assert h["bbox"] == TASK_HINT["bbox"] and h["zoom"] == 15
    assert h["reference_style"] == "osm-liberty" and "style" not in h


def test_country_hint_has_no_bbox_and_no_zoom():
    h = bench.agent_hint(TASK_HINT, {"hint": "country", "country": "jp"}, "osm-liberty")
    assert h["country"] == "jp" and "bbox" not in h and "zoom" not in h
    assert (h["width"], h["height"]) == (900, 700)


def test_wrong_bbox_hint_keeps_the_size_and_moves_the_centre():
    h = bench.agent_hint(TASK_HINT, {"hint": "wrong-bbox", "wrong_center": [133.5, 33.5]}, "osm-liberty")
    w, s, e, n = h["bbox"]
    assert (w + e) / 2 == pytest.approx(133.5) and (s + n) / 2 == pytest.approx(33.5)
    assert e - w == pytest.approx(0.1) and n - s == pytest.approx(0.1)


def test_unknown_hint_kind_is_an_error():
    with pytest.raises(ValueError):
        bench.agent_hint(TASK_HINT, {"hint": "nothing"}, "osm-liberty")


def test_prompt_keeps_the_skills_paragraph_only_with_skills():
    tpl = "A {{WORKDIR}}\n{{HINT_TEXT}}\n{{#SKILLS}}\nread skills\n{{/SKILLS}}\nB {{MINUTES}}\n"
    with_s = bench.fill_prompt(tpl, "/work", True, 30, "hint line")
    without = bench.fill_prompt(tpl, "/work", False, 30, "hint line")
    assert "read skills" in with_s and "read skills" not in without
    assert "{{" not in with_s and "{{" not in without
    assert "A /work" in without and "B 30" in without and "hint line" in without


def _task(tmp_path):
    t = tmp_path / "tasks" / "T1"
    (t / "task").mkdir(parents=True)
    (t / "truth").mkdir()
    (t / "task" / "image.png").write_bytes(b"png")
    (t / "task" / "hint.json").write_text(json.dumps(TASK_HINT))
    (t / "truth" / "truth.json").write_text("{}")
    return t


def test_baseline_workdir_holds_only_the_task(tmp_path):
    t = _task(tmp_path)
    d = bench.prepare_workdir(ROOT, "HEAD", tmp_path / "w", t, {"hint": "bbox"}, "osm-liberty", skills=False)
    names = sorted(str(p.relative_to(d)) for p in d.rglob("*"))
    assert names == ["task", "task/hint.json", "task/image.png"]


def test_skills_workdir_has_the_skills_and_no_evals_and_no_truth(tmp_path):
    t = _task(tmp_path)
    d = bench.prepare_workdir(ROOT, "HEAD", tmp_path / "w", t, {"hint": "bbox"}, "osm-liberty", skills=True)
    assert (d / "AGENTS.md").exists() and (d / ".agents" / "skills" / "georef-gates" / "SKILL.md").exists()
    assert not (d / "evals").exists() and not (d / ".git").exists()
    assert not any(p.name == "truth.json" for p in d.rglob("*"))
    assert json.loads((d / "task" / "hint.json").read_text())["reference_style"] == "osm-liberty"


def test_workdir_must_be_new(tmp_path):
    t = _task(tmp_path)
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "x").write_text("x")
    with pytest.raises(SystemExit):
        bench.prepare_workdir(ROOT, "HEAD", tmp_path / "w", t, {"hint": "bbox"}, "osm-liberty", skills=False)


@pytest.mark.parametrize("answer,score,negative,exit_code,expected", [
    (None, None, False, 0, "no_answer"),
    (None, None, False, 124, "timeout"),
    ({"status": "ok"}, {"status": "scored", "max_pct_radius": 0.5}, False, 124, "accurate"),
    ({"status": "failed"}, None, False, 0, "declared_failure"),
    ({"status": "ok"}, {"status": "scored", "max_pct_radius": 0.5}, False, 0, "accurate"),
    ({"status": "ok"}, {"status": "scored", "max_pct_radius": 7.0}, False, 0, "inaccurate"),
    ({"status": "ok"}, {"status": "unfittable"}, False, 0, "invalid_answer"),
    ("not json", None, False, 0, "invalid_answer"),
    ({"status": "failed"}, None, True, 0, "correct_reject"),
    ({"status": "ok"}, {"status": "scored", "max_pct_radius": 900.0}, True, 0, "false_accept"),
    (None, None, True, 0, "no_answer"),
])
def test_outcome(answer, score, negative, exit_code, expected):
    assert bench.outcome(answer, score, negative, exit_code, accurate_pct=1.0) == expected


def test_runner_failure_is_not_graded():
    assert bench.outcome(None, None, False, 1, accurate_pct=1.0, provider_error=True) == "provider_error"


def test_runner_scripts_dry_run_puts_the_time_limit_inside_the_container(tmp_path):
    w = tmp_path / "w"
    w.mkdir()
    p = tmp_path / "p.md"
    p.write_text("x")
    home = tmp_path / "codex"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    r = subprocess.run([str(ROOT / "evals/agents/run_codex_docker.sh"), "--dry-run", "--prompt", str(p), str(w)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                                                            "EVAL_CODEX_HOME": str(home), "EVAL_MINUTES": "7"})
    assert r.returncode == 0, r.stderr
    assert "timeout 7m codex exec" in r.stdout.replace("\\ ", " ")
    assert "--memory=16g" in r.stdout and "--cpus=8" in r.stdout


def test_gemini_runner_dry_run_puts_the_time_limit_inside_the_container(tmp_path):
    w = tmp_path / "w"
    w.mkdir()
    p = tmp_path / "p.md"
    p.write_text("x")
    state = tmp_path / "gem"
    (state / "antigravity-cli").mkdir(parents=True)
    (state / "antigravity-cli" / "antigravity-oauth-token").write_text("t")
    r = subprocess.run([str(ROOT / "evals/agents/run_gemini_docker.sh"), "--dry-run", "--prompt", str(p), str(w)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                                                            "EVAL_GEMINI_HOME": str(state), "EVAL_MINUTES": "7"})
    assert r.returncode == 0, r.stderr
    assert "exec\\ timeout" in r.stdout and " 7m " in r.stdout and "gemini-3.8-flash-low" in r.stdout


def test_public_osm_servers_are_found_in_a_log():
    assert bench.public_osm_hits("curl https://nominatim.openstreetmap.org/search?q=x") == ["nominatim.openstreetmap.org"]
    assert bench.public_osm_hits("GET https://tile.openstreetmap.org/15/1/2.png and https://overpass-api.de/api") == [
        "overpass-api.de", "tile.openstreetmap.org"]
    assert bench.public_osm_hits("Do not call nominatim.openstreetmap.org, tile.openstreetmap.org, overpass-api.de") == []
    assert bench.public_osm_hits("https://nominatim.yuiseki.net/search and tile.yuiseki.net") == []


# Level 5: a map inside a document. Answers are in pixels of the page drawn at the task's dpi.

def test_doc_answer_is_moved_into_the_map_rectangle():
    a = {"status": "ok", "image": {"width": 1240, "height": 1754}, "method": "affine",
         "gcps": [{"col": 110.0, "row": 220.0, "lon": 1, "lat": 2}]}
    b = bench.doc_answer_in_box(a, (100.0, 200.0, 400.0, 500.0))
    assert b["gcps"][0]["col"] == pytest.approx(10.0) and b["gcps"][0]["row"] == pytest.approx(20.0)
    assert b["image"] == {"width": 300, "height": 300}
    assert a["gcps"][0]["col"] == 110.0  # the answer itself is left as it was


def test_doc_box_is_the_map_rectangle_in_page_pixels():
    assert bench.doc_box({"map_pt": [72.0, 144.0, 360.0, 288.0]}, 150) == pytest.approx((150.0, 300.0, 900.0, 900.0))


# Level 6: unit positions against the published points of the same map.

def test_points_are_matched_one_to_one_within_the_radius():
    ref = [(30.0, 5.0), (30.1, 5.0), (31.0, 6.0)]
    pred = [(30.0, 5.001), (30.0, 5.002), (31.5, 6.0)]
    m = bench.match_points(pred, ref, radius_km=2.0)
    assert m["matched"] == 1  # two predictions near one reference count once
    assert m["precision"] == pytest.approx(1 / 3) and m["recall"] == pytest.approx(1 / 3)


def test_no_prediction_has_zero_recall_and_no_precision():
    m = bench.match_points([], [(30.0, 5.0)], radius_km=2.0)
    assert m["recall"] == 0 and m["precision"] is None


def test_points_of_a_geojson_are_read_in_lon_lat():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.5, 4.5]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4]]}, "properties": {}},
        {"type": "Feature", "geometry": None, "properties": {}}]}
    assert bench.points_of(fc) == [(30.5, 4.5), (1, 2), (3, 4)]


@pytest.mark.parametrize("m,expected", [
    ({"precision": 0.9, "recall": 0.85}, "accurate"),
    ({"precision": 0.9, "recall": 0.5}, "inaccurate"),
    ({"precision": None, "recall": 0.0}, "inaccurate"),
])
def test_pko_outcome(m, expected):
    assert bench.pko_outcome(m, threshold=0.8) == expected


def test_doc_and_pko_workdirs_hold_the_document_and_a_hint(tmp_path):
    t = tmp_path / "tasks" / "D"
    (t / "task").mkdir(parents=True)
    (t / "truth").mkdir()
    (t / "task" / "document.pdf").write_bytes(b"%PDF")
    (t / "truth" / "truth.json").write_text("{}")
    d = bench.prepare_workdir(ROOT, "HEAD", tmp_path / "w", t, {"type": "doc", "hint": "country", "country": "jp",
                                                                  "page_px": [1240, 1754], "dpi": 150}, "osm-liberty", False)
    assert sorted(p.name for p in (d / "task").iterdir()) == ["document.pdf", "hint.json"]
    h = json.loads((d / "task" / "hint.json").read_text())
    assert h["country"] == "jp" and h["dpi"] == 150 and h["page_px"] == [1240, 1754]
    t2 = tmp_path / "tasks" / "P"
    (t2 / "task").mkdir(parents=True)
    (t2 / "task" / "map.pdf").write_bytes(b"%PDF")
    d2 = bench.prepare_workdir(ROOT, "HEAD", tmp_path / "w2", t2, {"type": "pko"}, "osm-liberty", False)
    assert sorted(p.name for p in (d2 / "task").iterdir()) == ["hint.json", "map.pdf"]


def test_pdf_by_sha_finds_the_source_without_its_name(tmp_path):
    import hashlib
    src = tmp_path / "src"; (src / "2025").mkdir(parents=True)
    (src / "2025" / "a.pdf").write_bytes(b"one"); (src / "b.pdf").write_bytes(b"two")
    index = tmp_path / "index.json"
    sha = hashlib.sha256(b"one").hexdigest()
    assert bench.pdf_by_sha(src, sha, index) == src / "2025" / "a.pdf"
    assert json.loads(index.read_text())[sha] == "2025/a.pdf"
    (src / "c.pdf").write_bytes(b"three")  # not in the index yet: the index is rebuilt
    assert bench.pdf_by_sha(src, hashlib.sha256(b"three").hexdigest(), index) == src / "c.pdf"
    with pytest.raises(SystemExit):
        bench.pdf_by_sha(src, "0" * 64, index)


def test_pko_tasks_name_no_source_file():
    for t in bench.load_spec()["tasks"]:
        if t.get("type") == "pko":
            assert "file" not in t, t["id"]


@pytest.mark.parametrize("agent,secret,cli", [("claude", "oauth_token", "claude -p"), ("qoder", "pat", "qodercli -p"),
                                              ("opencode", None, "opencode run")])
def test_new_runners_dry_run_puts_the_time_limit_inside_the_container_and_keep_the_secret_out(tmp_path, agent, secret, cli):
    w = tmp_path / "w"
    w.mkdir()
    p = tmp_path / "p.md"
    p.write_text("x")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "EVAL_MINUTES": "7"}
    if secret:
        home = tmp_path / agent
        home.mkdir()
        (home / secret).write_text("SECRET-VALUE\n")
        env[f"EVAL_{agent.upper()}_HOME"] = str(home)
    r = subprocess.run([str(ROOT / f"evals/agents/run_{agent}_docker.sh"), "--dry-run", "--prompt", str(p), str(w),
                        *bench.MODELS[agent]], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = r.stdout.replace("\\ ", " ")
    assert f"timeout 7m {cli}" in out
    assert "--memory=16g" in out and "--cpus=8" in out and "--cap-drop=ALL" in out
    assert f"geo-ref-skills-evals-{agent}" in out
    assert "SECRET-VALUE" not in out


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini", "opencode", "qoder"])
def test_new_runners_refuse_a_workdir_with_evaluation_material(tmp_path, agent):
    w = tmp_path / "w"
    (w / "evals").mkdir(parents=True)
    p = tmp_path / "p.md"
    p.write_text("x")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    for name, f in [("CLAUDE", "oauth_token"), ("QODER", "pat"), ("CODEX", "auth.json")]:
        (tmp_path / name).mkdir(exist_ok=True)
        (tmp_path / name / f).write_text("t")
        env[f"EVAL_{name}_HOME"] = str(tmp_path / name)
    r = subprocess.run([str(ROOT / f"evals/agents/run_{agent}_docker.sh"), "--dry-run", "--prompt", str(p), str(w)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "contains evals/" in r.stderr


def test_every_agent_has_a_runner_and_a_recorded_model():
    assert set(bench.RUNNERS) == {"claude", "codex", "gemini", "opencode", "qoder"}
    assert all(p.exists() for p in bench.RUNNERS.values())
    assert bench.model_record("gemini", {}) == ["gemini-3.8-flash-low"]
    assert bench.model_record("opencode", {"EVAL_MODEL": "opencode/glm-5.3-flash-free"}) == ["opencode/glm-5.3-flash-free"]
    assert bench.model_record("claude", {"EVAL_MODEL": "x"}) == ["--model", "claude-sonnet-5-5"]


def test_preflight_names_the_services_that_do_not_answer():
    # a broken environment must not be graded as the agent's failure: the run is not started
    ok = bench.preflight({"tiles": "https://t/0/0/0.png", "geocoder": "https://g/status"},
                         fetch=lambda url: 200 if url.startswith("https://t/") else 503)
    assert ok == ["geocoder (https://g/status): 503"]
    assert bench.preflight({"tiles": "https://t/x"}, fetch=lambda url: 200) == []


def test_preflight_counts_an_exception_as_a_failure():
    def boom(url):
        raise OSError("refused")
    assert bench.preflight({"tiles": "https://t/x"}, fetch=boom) == ["tiles (https://t/x): OSError('refused')"]


def test_every_prompt_names_the_services_the_preflight_checks():
    for name in ("prompt.md", "prompt-doc.md", "prompt-pko.md"):
        text = (Path(bench.HERE) / name).read_text()
        assert "tile.yuiseki.net" in text and "nominatim.yuiseki.net" in text
    assert all(u.startswith(("https://tile.yuiseki.net/", "https://nominatim.yuiseki.net/")) for u in bench.SERVICES.values())


def test_the_image_of_a_run_is_recorded_by_id():
    rec = bench.image_record("codex", {}, inspect=lambda image: "sha256:abc" if image == "geo-ref-skills-evals-codex" else None)
    assert rec == {"image": "geo-ref-skills-evals-codex", "image_id": "sha256:abc"}
    rec = bench.image_record("codex", {"EVAL_IMAGE": "x:pre"}, inspect=lambda image: None)
    assert rec == {"image": "x:pre", "image_id": None}


def _row(agent, cond, task, rep, outcome):
    return {"agent": agent, "cond": cond, "task": task, "rep": str(rep), "outcome": outcome}


def test_summary_counts_reps_and_leaves_provider_errors_out():
    rows = [_row("codex", "skills", "L1", 1, "accurate"), _row("codex", "skills", "L1", 2, "inaccurate"),
            _row("codex", "skills", "L1", 3, "provider_error"), _row("gemini", "skills", "L1", 1, "accurate")]
    s = {(r["agent"], r["cond"], r["task"]): r for r in bench.summarize(rows)}
    assert s[("codex", "skills", "L1")]["n"] == 2 and s[("codex", "skills", "L1")]["good"] == 1
    assert s[("codex", "skills", "L1")]["outcomes"] == "accurate:1,inaccurate:1"
    assert s[("codex", "skills", "L1")]["provider_errors"] == 1
    assert s[("gemini", "skills", "L1")]["n"] == 1 and s[("gemini", "skills", "L1")]["single"]


def test_summary_counts_a_correct_reject_as_good():
    s = bench.summarize([_row("codex", "skills", "N", 1, "correct_reject"), _row("codex", "skills", "N", 2, "false_accept")])
    assert s[0]["good"] == 1 and s[0]["n"] == 2 and not s[0]["single"]


def _dry_run_env(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    for name, f in [("CLAUDE", "oauth_token"), ("QODER", "pat"), ("CODEX", "auth.json")]:
        (tmp_path / name).mkdir(exist_ok=True)
        (tmp_path / name / f).write_text("t")
        env[f"EVAL_{name}_HOME"] = str(tmp_path / name)
    (tmp_path / "GEMINI" / "antigravity-cli").mkdir(parents=True, exist_ok=True)
    (tmp_path / "GEMINI" / "antigravity-cli" / "antigravity-oauth-token").write_text("t")
    env["EVAL_GEMINI_HOME"] = str(tmp_path / "GEMINI")
    return env


BLOCKED = (bench.HERE / "blocked-hosts.txt")


def test_the_blocked_hosts_cover_the_public_osm_servers_the_score_looks_for():
    hosts = [h for h in BLOCKED.read_text().split() if not h.startswith("#")]
    for h in ["tile.openstreetmap.org", "a.tile.openstreetmap.org", "nominatim.openstreetmap.org", "overpass-api.de",
              "overpass.kumi.systems", "api.openstreetmap.org"]:
        assert h in hosts
        assert bench.public_osm_hits(f"https://{h}/x") == [h]
    assert not any("yuiseki" in h for h in hosts)


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini", "opencode", "qoder"])
def test_every_runner_makes_the_public_osm_servers_unreachable(tmp_path, agent):
    # the prompt forbids them, and a Qoder run called overpass-api.de anyway (2026-11-16): the sandbox enforces it
    w = tmp_path / "w"
    w.mkdir()
    p = tmp_path / "p.md"
    p.write_text("x")
    r = subprocess.run([str(ROOT / f"evals/agents/run_{agent}_docker.sh"), "--dry-run", "--prompt", str(p), str(w)],
                       capture_output=True, text=True, env=_dry_run_env(tmp_path))
    assert r.returncode == 0, r.stderr
    for h in ["overpass-api.de", "tile.openstreetmap.org", "nominatim.openstreetmap.org"]:
        assert f"--add-host={h}:0.0.0.0" in r.stdout, (agent, h)
    assert "yuiseki.net:0.0.0.0" not in r.stdout


def test_a_run_with_another_model_is_kept_apart_from_the_default_model():
    # opencode with hy4-flash-free and with the default deepseek must not share runs/<agent>/ (nor a row of the score)
    assert bench.run_label("opencode", {}) == "opencode"
    assert bench.run_label("opencode", {"EVAL_MODEL": "opencode/deepseek-v4.1-flash-free"}) == "opencode"
    assert bench.run_label("opencode", {"EVAL_MODEL": "opencode/hy4-flash-free"}) == "opencode@hy4-flash-free"
    assert bench.run_label("gemini", {"EVAL_MODEL": "gemini-3.8-flash-low"}) == "gemini"
    assert bench.run_label("codex", {"EVAL_MODEL": "x"}) == "codex"  # codex takes its model as an argument


def test_opencode_runner_can_pin_the_model_catalogue(tmp_path):
    # opencode looks a model up in its bundled catalogue before the fetched one arrives (seconds later), so a model
    # newer than the release (hy4-flash-free, 2026-11-17) was "not found" in 3 of 4 fresh containers
    w = tmp_path / "w"
    w.mkdir()
    p = tmp_path / "p.md"
    p.write_text("x")
    cat = tmp_path / "models.json"
    cat.write_text("{}")
    env = {**_dry_run_env(tmp_path), "EVAL_OPENCODE_MODELS": str(cat)}
    r = subprocess.run([str(ROOT / "evals/agents/run_opencode_docker.sh"), "--dry-run", "--prompt", str(p), str(w)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert f"-v {cat}:/opt/opencode-models.json:ro" in r.stdout
    assert "-e OPENCODE_MODELS_PATH=/opt/opencode-models.json" in r.stdout
    assert "-e OPENCODE_DISABLE_MODELS_FETCH=1" in r.stdout
    r = subprocess.run([str(ROOT / "evals/agents/run_opencode_docker.sh"), "--dry-run", "--prompt", str(p), str(w)],
                       capture_output=True, text=True, env=_dry_run_env(tmp_path))
    assert "OPENCODE_MODELS_PATH" not in r.stdout
    env["EVAL_OPENCODE_MODELS"] = str(tmp_path / "missing.json")
    r = subprocess.run([str(ROOT / "evals/agents/run_opencode_docker.sh"), "--dry-run", "--prompt", str(p), str(w)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2


def test_the_pinned_model_catalogue_is_recorded_by_hash(tmp_path):
    c = tmp_path / "models.json"
    c.write_text("{}")
    assert bench.catalogue_record({}) == {}
    rec = bench.catalogue_record({"EVAL_OPENCODE_MODELS": str(c)})
    assert rec == {"model_catalogue_sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"}
