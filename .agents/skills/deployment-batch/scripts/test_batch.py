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
