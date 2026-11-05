# uvx --with numpy --with opencv-python-headless --with cairosvg --with pytest pytest scripts/test_render_units.py
import json
import numpy as np
import render_units as ru

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><path d="M 5,5 H 595 V 395 H 5 Z" '
       'style="fill:#ff0000;stroke:#000000;stroke-width:10"/></svg>')


def feat(lon, lat, arm, echelon=None, label="X"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"arm": arm, "echelon": echelon, "label": label}}


def test_mercator_origin_and_antimeridian():
    assert ru.to_mercator(0, 0) == (0.0, 0.0) or max(map(abs, ru.to_mercator(0, 0))) < 1e-6
    assert abs(ru.to_mercator(180, 0)[0] - ru.ORIGIN) < 1e-6


def test_headquarters_of_every_rank_share_a_symbol_and_unknown_arms_have_none():
    assert ru.symbol_key("sector headquarters") == ru.symbol_key("force headquarters") == "headquarters"
    assert ru.symbol_key("military observers") is None


def test_size_marks():
    assert ru.mark_geometry("company") == (1, "bar") and ru.mark_geometry("platoon") == (3, "dot")
    assert ru.mark_geometry(None) is None


def test_stacked_units_share_a_point():
    gt = [0.0, 1000.0, 0, 0.0, 0, -1000.0]
    g = ru.stack_groups([feat(0.0001, 0.0001, "infantry"), feat(0.0001, 0.0001, "medical")], gt)
    assert len(g) == 1 and len(next(iter(g.values()))) == 2


def test_render_draws_the_symbol_and_a_plain_frame_with_letters(tmp_path):
    (tmp_path / "infantry.svg").write_text(SVG)
    ref = np.full((300, 300, 3), 255, np.uint8)
    gt = [0.0, 1000.0, 0, 0.0, 0, -1000.0]  # 1 px = 1000 m
    x, y = 100, 150
    lon = 1000.0 * x / ru.ORIGIN * 180
    fs = [feat(lon, 0, "infantry", "company")]
    out, used = ru.render(fs, ref, [-0.0, 1000.0, 0, 150 * 1000.0, 0, -1000.0], tmp_path, height=26)
    assert used == {"infantry"}
    assert (out != ref).any()
    out2, used2 = ru.render([feat(lon, 0, "military observers")], ref, [0.0, 1000.0, 0, 150000.0, 0, -1000.0], tmp_path)
    assert used2 == set() and (out2 != ref).any()
    # an arm whose symbol file is missing is a lettered frame and is not credited
    out3, used3 = ru.render([feat(lon, 0, "military police")], ref, [0.0, 1000.0, 0, 150000.0, 0, -1000.0], tmp_path)
    assert used3 == set()


def test_credits_name_the_artist_and_licence(tmp_path):
    (tmp_path / "sources.json").write_text(json.dumps({"infantry": {"artist": "CdnMCG", "licence": "CC BY-SA 4.0"}}))
    lines = ru.credit_lines({"infantry"}, tmp_path)
    assert "CdnMCG" in lines[1] and "CC BY-SA 4.0" in lines[1] and "OpenStreetMap" in lines[0]
