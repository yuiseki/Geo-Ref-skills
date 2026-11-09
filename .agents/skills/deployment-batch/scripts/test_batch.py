# uvx --with pytest pytest scripts/test_batch.py
import batch as B


def test_the_mission_is_the_first_acronym_found_whole_in_the_title_then_the_name():
    assert B.mission_of("MONUSCO 7777 R60 Jun25 120%", "x") == "MONUSCO"
    assert B.mission_of("Map", "UNFICYP_2930_R100") == "UNFICYP"
    assert B.mission_of("monusco map") == "MONUSCO"
    assert B.mission_of("UNMISSING map") is None  # whole words only, not a prefix
    assert B.mission_of(None, "") is None


def test_the_date_is_the_creation_date_else_the_modification_date():
    assert B.pdf_date("D:20250601120000+00'00'", "D:20260101") == "20250601"
    assert B.pdf_date(None, "D:20190628") == "20190628"
    assert B.pdf_date("garbage", None) == "00000000"


def test_every_vector_frame_among_the_first_eight_is_tried_besides_the_first_three():
    cs = [{"from": {}} for _ in range(10)]
    cs[5]["from"]["frame"] = True
    cs[9]["from"]["frame"] = True  # beyond the first eight
    cs[1]["from"]["frame"] = True
    assert B.to_try(cs) == [0, 1, 2, 5]


def test_each_mission_lists_country_codes_and_no_map_number():
    import re
    for m, cc in B.MISSIONS.items():
        assert re.fullmatch(r"[a-z]{2}(,[a-z]{2})*", cc), m
        assert not re.search(r"\d", m), m


def test_after_a_pass_the_first_four_and_every_frame_are_tried_for_insets():
    cs = [{"from": {}} for _ in range(12)]
    cs[10]["from"]["frame"] = True
    assert B.to_try(cs, first=4, total=len(cs)) == [0, 1, 2, 3, 10]


def fake_steps(monkeypatch, name_status, grat_status, passes):
    """name-gcps answers name_status, graticule-gcps grat_status; the gates pass when `passes`."""
    import json
    calls = []

    def run(cmd, log):
        out = cmd[cmd.index("--out") + 1]
        tool = "graticule" if any("graticule_gcps.py" in str(c) for c in cmd) else "name"
        calls.append((tool, cmd[cmd.index("--method") + 1]))
        st = name_status if tool == "name" else grat_status
        a = {"status": st, "reason": "no", "tool": {"name": tool, "words_from": "pdf"}, "gcps": [{}] * 20}
        open(out, "w").write(json.dumps(a))
        return 0

    monkeypatch.setattr(B, "run", run)
    monkeypatch.setattr(B, "gates", lambda ans: {"passed": passes, "gates": [{"name": "loo_residual", "passed": passes, "max_px": 1.0}]})
    return calls


def cand():
    return [{"file": "cand-001.png", "dpi": 150, "page": 1, "from": {"kind": "rendered", "box_px": [66, 159, 1209, 1568]}}]


def test_a_map_whose_names_fail_is_tried_on_its_graticule(tmp_path, monkeypatch):
    # UNDOF, 2025: 7 towns fit (need 12); the frame is ticked every 5 minutes
    calls = fake_steps(monkeypatch, "failed", "ok", True)
    tried = []
    got = B.attempt(tmp_path / "m.pdf", "UNDOF", tmp_path, cand(), 0, tried)
    assert got["stage"] == "ok" and got["gcps_from"] == "graticule-gcps" and got["method"] == "affine"
    assert calls == [("name", "affine"), ("graticule", "affine")]


def test_the_graticule_is_not_tried_when_the_names_pass(tmp_path, monkeypatch):
    calls = fake_steps(monkeypatch, "ok", "ok", True)
    got = B.attempt(tmp_path / "m.pdf", "UNMISS", tmp_path, cand(), 0, [])
    assert got["gcps_from"] == "name-gcps" and calls == [("name", "affine")]


def test_a_graticule_failing_the_gates_is_tried_projective_then_given_up(tmp_path, monkeypatch):
    calls = fake_steps(monkeypatch, "failed", "ok", False)
    tried = []
    assert B.attempt(tmp_path / "m.pdf", "UNDOF", tmp_path, cand(), 0, tried) is None
    assert calls == [("name", "affine"), ("graticule", "affine"), ("graticule", "projective")]


def test_a_mission_with_a_utm_grid_passes_its_zone_to_the_graticule(tmp_path, monkeypatch):
    # UNIFIL's maps (2025) are gridded in UTM metres (700000E, 3700000N) and do not print the zone; south Lebanon
    # is in zone 36 (30 to 36 E)
    import json
    cmds = []

    def run(cmd, log):
        cmds.append(cmd)
        out = cmd[cmd.index("--out") + 1]
        open(out, "w").write(json.dumps({"status": "failed", "reason": "no", "tool": {}}))
        return 0

    monkeypatch.setattr(B, "run", run)
    B.attempt(tmp_path / "m.pdf", "UNIFIL", tmp_path, cand(), 0, [])
    grat = [c for c in cmds if any("graticule_gcps.py" in str(x) for x in c)]
    assert grat and grat[0][grat[0].index("--utm-zone") + 1] == "36N"
    cmds.clear()
    B.attempt(tmp_path / "m.pdf", "UNDOF", tmp_path, cand(), 0, [])
    assert not any("--utm-zone" in c for c in cmds)


def test_the_graticule_writes_its_own_answer_beside_the_names(tmp_path, monkeypatch):
    # a graticule's declared failure must not overwrite the names' answer whose gates are kept (MONUSCO 2025)
    calls = fake_steps(monkeypatch, "ok", "failed", False)
    outs = []
    run0 = B.run

    def run(cmd, log):
        outs.append(cmd[cmd.index("--out") + 1].rsplit("/", 1)[1])
        return run0(cmd, log)

    monkeypatch.setattr(B, "run", run)
    B.attempt(tmp_path / "m.pdf", "MONUSCO", tmp_path, cand(), 0, [])
    assert outs == ["answer.c1.affine.json", "answer.c1.projective.json", "answer.c1.grid_affine.json"]


def test_a_step_that_runs_too_long_is_stopped_with_everything_it_started():
    # subprocess's timeout killed only systemd-run's own process; name-gcps and its tesseract were left running in
    # the scope, one for 29 hours (2026-11-06). The scope itself must end at the step's time limit.
    i = B.CAP.index("RuntimeMaxSec=%d" % B.STEP_SECONDS)
    assert B.CAP[i - 1] == "-p" and B.STEP_SECONDS < B.STEP_TIMEOUT


def test_a_timed_out_map_is_marked_for_retry_not_as_its_result():
    # the 23 maps that timed out in the 2017-2019 batches all gave ok or failed when run again: the time limit
    # depends on the machine's load, not on the map (2026-11-09)
    import subprocess
    e = subprocess.TimeoutExpired(["systemd-run"], 1860)
    assert B.outcome_of(e, retries=0) == {"stage": "retry", "retries": 1, "why": repr(e)[:300]}
    assert B.outcome_of(e, retries=B.MAX_RETRIES - 1)["stage"] == "error"   # timed out every time: a result
    assert B.outcome_of(ValueError("x"), retries=0)["stage"] == "error"


def test_resuming_drops_the_lines_to_retry_and_counts_them():
    import json
    lines = [json.dumps(x) for x in (
        {"file": "a.pdf", "stage": "ok"},
        {"file": "b.pdf", "stage": "retry", "retries": 1},
        {"file": "c.pdf", "stage": "error", "why": "TimeoutExpired(['systemd-run', ...], 1860)"},  # before retries existed
        {"file": "d.pdf", "stage": "error", "why": "ValueError('x')"})]
    keep, retries = B.pending(lines)
    assert [json.loads(l)["file"] for l in keep] == ["a.pdf", "d.pdf"]
    assert retries == {"b.pdf": 1, "c.pdf": 1}


def test_a_resumed_batch_has_one_line_per_pdf(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    src = tmp_path / "pdfs"; src.mkdir()
    for n in ("a.pdf", "b.pdf"):
        (src / n).write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "work"
    calls = []

    def one(pdf, mission, d):
        calls.append(pdf.name)
        if pdf.name == "b.pdf" and calls.count("b.pdf") == 1:
            raise subprocess.TimeoutExpired(["x"], 1)
        return {"stage": "failed", "tried": []}

    monkeypatch.setattr(B, "one", one)
    monkeypatch.setattr(sys, "argv", ["batch.py", "--src", str(src), "--out", str(out)])
    B.main()
    first = [json.loads(l) for l in open(out / "results.jsonl")]
    assert {r["file"]: r["stage"] for r in first} == {"a.pdf": "failed", "b.pdf": "retry"}
    B.main()
    rows = [json.loads(l) for l in open(out / "results.jsonl")]
    assert sorted(r["file"] for r in rows) == ["a.pdf", "b.pdf"]
    assert {r["file"]: r["stage"] for r in rows} == {"a.pdf": "failed", "b.pdf": "failed"}
    assert calls == ["a.pdf", "b.pdf", "b.pdf"]


def test_a_step_ended_by_the_scope_time_limit_counts_as_a_timeout(tmp_path, monkeypatch):
    # the scope's RuntimeMaxSec ends the step before subprocess's own timeout: without this the step only leaves no
    # answer, and the map is recorded as failed though it was never given the time to finish
    import subprocess
    import pytest
    clock = iter([0.0, B.STEP_SECONDS + 0.5])
    monkeypatch.setattr(B.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(B.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    with pytest.raises(subprocess.TimeoutExpired):
        B.run(["true"], tmp_path / "log")


def test_a_step_that_fails_quickly_is_not_a_timeout(tmp_path, monkeypatch):
    import subprocess
    clock = iter([0.0, 3.0])
    monkeypatch.setattr(B.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(B.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    assert B.run(["false"], tmp_path / "log") == 1
