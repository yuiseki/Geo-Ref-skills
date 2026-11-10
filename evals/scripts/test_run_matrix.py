# uvx --with pytest pytest scripts/test_run_matrix.py
import run_matrix


def test_classify_all_four_outcomes():
    assert run_matrix.classify(False, True, 0.2, 1.0) == "ok"
    assert run_matrix.classify(False, True, 5.0, 1.0) == "gate_hole"
    assert run_matrix.classify(False, False, 0.2, 1.0) == "over_strict"
    assert run_matrix.classify(False, False, 5.0, 1.0) == "refused"
    assert run_matrix.classify(True, False, None, 1.0) == "refused"


def test_gates_passed_without_a_score_is_a_hole():
    assert run_matrix.classify(False, True, None, 1.0) == "gate_hole"


def test_task_grid_is_the_full_product_with_unique_ids():
    m = {"level": 1, "places": {"a": [0, 0], "b": [1, 1]}, "styles": ["s"], "kinds": ["similarity", "affine"],
         "strengths": [0.25, 1.0], "seeds": [1, 2, 3]}
    ts = list(run_matrix.tasks(m))
    assert len(ts) == 2 * 1 * 2 * 2 * 3
    assert len({t["id"] for t in ts}) == len(ts)


def test_negative_controls_move_the_hint_to_another_place():
    m = {"level": 1, "places": {"a": [10.0, 20.0], "b": [30.0, 40.0]}, "styles": ["s"],
         "negatives": {"pairs": [["a", "b"]], "kinds": ["projective"], "strengths": [0.5], "seeds": [1, 2]}}
    ns = list(run_matrix.negatives(m))
    assert len(ns) == 2
    assert ns[0]["center"] == [10.0, 20.0] and ns[0]["wrong_center"] == [30.0, 40.0]
    assert run_matrix.shifted_bbox([9.0, 19.5, 11.0, 20.5], [30.0, 40.0]) == [29.0, 39.5, 31.0, 40.5]
    assert list(run_matrix.negatives({"level": 1})) == []


def test_photometrics_are_an_axis_and_default_to_none():
    m = {"level": 2, "places": {"a": [0, 0]}, "styles": ["s"], "kinds": ["similarity"], "strengths": [0.5], "seeds": [1]}
    assert [t["photometric"] for t in run_matrix.tasks(m)] == ["none"]
    m["photometrics"] = ["none", "gray", "binary"]
    ts = list(run_matrix.tasks(m))
    assert [t["photometric"] for t in ts] == ["none", "gray", "binary"]
    assert len({t["id"] for t in ts}) == 3


def test_attempts_from_either_form():
    assert run_matrix.attempts({}) == [{"registrar": "feature-registration", "args": []}]
    m = {"registrars": ["feature-registration", "cross-style-registration"],
         "registrar_args": {"cross-style-registration": ["--mask", "lines"]}}
    assert run_matrix.attempts(m)[1] == {"registrar": "cross-style-registration", "args": ["--mask", "lines"]}
    a = [{"registrar": "cross-style-registration", "ref_style": "roads-minimal", "args": ["--mask", "lines"]}]
    assert run_matrix.attempts({"attempts": a}) == a


def test_zooms_are_an_axis_when_given():
    m = {"level": 4, "zoom": 15, "places": {"a": [0, 0]}, "styles": ["s"], "kinds": ["similarity"], "strengths": [0.5],
         "seeds": [1]}
    assert [t["zoom"] for t in run_matrix.tasks(m)] == [15]
    m["zooms"] = [14, 16]
    ts = list(run_matrix.tasks(m))
    assert [t["zoom"] for t in ts] == [14, 16] and len({t["id"] for t in ts}) == 2


def test_level4_hint_comes_from_place_hint_scale_or_is_a_refusal():
    ok = {"status": "ok", "bbox": [1, 2, 3, 4], "scale": {"status": "ok", "bbox": [1.5, 2.5, 2.5, 3.5], "zoom": 16,
                                                          "zooms": [16, 15]}}
    assert run_matrix.hint_from_place_hint(ok) == {"bbox": [1.5, 2.5, 2.5, 3.5], "zoom": 16, "zooms": [16, 15],
                                                    "source": "place-hint"}
    no_scale = {"status": "ok", "bbox": [1, 2, 3, 4], "scale": {"status": "failed", "reason": "2 of 3 names"}}
    assert run_matrix.hint_from_place_hint(no_scale) is None
    assert run_matrix.hint_from_place_hint({"status": "failed", "reason": "support 1"}) is None


def test_country_for_a_place_overrides_the_matrix_country():
    m = {"countrycodes": "jp", "countrycodes_for": {"london": "gb"}}
    assert run_matrix.country_for(m, "london") == "gb"
    assert run_matrix.country_for(m, "tokyo") == "jp"
    assert run_matrix.country_for({}, "tokyo") == "jp"


def test_a_reference_too_large_to_fetch_is_a_declared_failure_not_an_error():
    # a wrong scale from the names (a whole page read as the map) asks for 550 tiles; the fetcher refuses
    err = "fetch_reference.py exited 1: ValueError: 550 tiles needed, more than max_tiles=400"
    assert "550 tiles" in run_matrix.reference_refusal(err)
    assert run_matrix.reference_refusal("exited 1: TimeoutError: The read operation timed out") is None


def test_anchor_boxes_become_hints_of_one_zoom_each_in_order():
    ph = {"status": "failed", "anchors": [
        {"name": "Kanazawa", "hints": [{"zoom": 14, "bbox": [1, 2, 3, 4]}, {"zoom": 15, "bbox": [1.5, 2.5, 2.5, 3.5]}]},
        {"name": "Kanazawa", "hints": [{"zoom": 14, "bbox": [5, 6, 7, 8]}]}]}
    hs = run_matrix.anchor_hints(ph)
    assert [(h["zoom"], h["zooms"], h["bbox"][0]) for h in hs] == [(14, [14], 1), (15, [15], 1.5), (14, [14], 5)]
    assert all(h["source"] == "place-hint-anchor" and h["anchor"] == "Kanazawa" for h in hs)
    assert run_matrix.anchor_hints({"status": "failed"}) == []


def test_a_negative_control_moves_every_anchor_box_to_the_wrong_place():
    ph = {"status": "failed", "anchors": [
        {"name": "Kanazawa", "hints": [{"zoom": 14, "bbox": [136.6, 36.5, 136.7, 36.6]}]}]}
    hs = run_matrix.anchor_hints(ph, wrong_center=[141.35, 43.06])
    w, s, e, n = hs[0]["bbox"]
    assert abs((w + e) / 2 - 141.35) < 1e-9 and abs((s + n) / 2 - 43.06) < 1e-9
    assert abs((e - w) - 0.1) < 1e-9 and abs((n - s) - 0.1) < 1e-9


def test_no_anchor_passing_the_gates_is_a_correct_reject_for_a_negative_and_a_refusal_otherwise():
    t = {"id": "x", "place": "kanazawa"}
    assert run_matrix.anchors_failed(t, "no names", 3)["outcome"] == "refused"
    neg = run_matrix.anchors_failed({**t, "wrong_center": [1, 2]}, "no names", 3)
    assert neg["outcome"] == "correct_reject" and "wrong_center" not in neg
    assert "3 anchor boxes, none passed the gates" in neg["error"]


def test_negative_controls_take_the_zoom_axis_when_the_matrix_has_one():
    m = {"level": 4, "places": {"a": [10.0, 20.0], "b": [30.0, 40.0]}, "styles": ["s"], "zooms": [14, 16],
         "negatives": {"pairs": [["a", "b"]], "kinds": ["projective"], "strengths": [0.5], "seeds": [1]}}
    ns = list(run_matrix.negatives(m))
    assert [(n["id"], n["zoom"]) for n in ns] == [("N4-a-on-b-z14-projective-s0.5-r1", 14),
                                                  ("N4-a-on-b-z16-projective-s0.5-r1", 16)]
    m1 = {**m, "level": 1, "zoom": 15}
    del m1["zooms"]
    assert [n["id"] for n in run_matrix.negatives(m1)] == ["N1-a-on-b-projective-s0.5-r1"]


def test_the_place_hint_key_changes_with_the_image_the_arguments_and_the_tool(tmp_path):
    img, tool = tmp_path / "image.png", tmp_path / "place_hint.py"
    img.write_bytes(b"map")
    tool.write_text("v1")
    k = run_matrix.content_key([img, tool], ["--countrycodes", "jp"], "tesseract 5.3.4")
    assert k == run_matrix.content_key([img, tool], ["--countrycodes", "jp"], "tesseract 5.3.4")
    assert k != run_matrix.content_key([img, tool], ["--countrycodes", "gb"], "tesseract 5.3.4")
    assert k != run_matrix.content_key([img, tool], ["--countrycodes", "jp"], "tesseract 5.5.0")
    tool.write_text("v2")
    assert k != run_matrix.content_key([img, tool], ["--countrycodes", "jp"], "tesseract 5.3.4")


def test_a_cached_result_is_copied_and_the_step_is_not_run_again(tmp_path):
    calls = []

    def produce(out):
        calls.append(out)
        out.write_text('{"status": "ok"}')

    a, b = tmp_path / "a" / "place_hint.json", tmp_path / "b" / "place_hint.json"
    a.parent.mkdir()
    b.parent.mkdir()
    cache = tmp_path / "cache"
    assert run_matrix.cached(a, "k1", cache, produce) is False
    assert run_matrix.cached(b, "k1", cache, produce) is True
    assert calls == [a] and b.read_text() == '{"status": "ok"}'
    assert run_matrix.cached(b, "k1", cache, produce) is True and calls == [a]  # an existing output is kept


def test_a_step_that_writes_nothing_leaves_nothing_in_the_cache(tmp_path):
    out = tmp_path / "place_hint.json"
    try:
        run_matrix.cached(out, "k1", tmp_path / "cache", lambda o: (_ for _ in ()).throw(RuntimeError("boom")))
    except RuntimeError:
        pass
    assert not (tmp_path / "cache" / "k1.json").exists()


def test_the_gates_output_is_named_by_the_gate_scripts_so_a_gate_change_is_checked_again(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "check_gcps.py").write_text("v1")
    (d / "test_check_gcps.py").write_text("tests do not count")
    a = run_matrix.gates_name(d)
    assert a.startswith("gates.") and a.endswith(".json") and a == run_matrix.gates_name(d)
    (d / "test_check_gcps.py").write_text("changed")
    assert run_matrix.gates_name(d) == a
    (d / "check_gcps.py").write_text("v2")
    assert run_matrix.gates_name(d) != a
