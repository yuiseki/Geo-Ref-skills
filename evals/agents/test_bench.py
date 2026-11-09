# uvx --with pytest --with numpy --with pyproj python -m pytest -q test_bench.py
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
