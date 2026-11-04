# uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with pytest pytest scripts/test_stitch_images.py
import numpy as np
from PIL import Image

import extract_images
import stitch_images
from test_extract_images import make_pdf


def picture(w, h, seed=0):
    g = np.random.default_rng(seed)
    return Image.fromarray(g.integers(0, 255, (h, w, 3), dtype=np.uint8))


def test_a_map_cut_into_strips_is_put_back_together(tmp_path):
    whole = picture(400, 300)
    strips = [whole.crop((0, y, 400, y + 100)) for y in (0, 100, 200)]
    # 300 x 225 pt in all, strips stacked from the top (PDF y grows upwards)
    make_pdf(tmp_path / "a.pdf", [(s, 50, 625 - 75 * (i + 1), 300, 75) for i, s in enumerate(strips)]
             + [(picture(64, 64, 1), 400, 50, 32, 32)])
    man = extract_images.extract(tmp_path / "a.pdf", tmp_path / "out")
    got = stitch_images.stitch(man, tmp_path / "out")
    assert len(got) == 1
    s = got[0]
    assert sorted(s["parts"]) == sorted(i["id"] for i in man["images"] if i["px"] == [400, 100])
    assert s["px"] == [400, 300] and s["page"] == 1
    assert s["bbox_pt"] == [50, 400, 350, 625] or np.allclose(s["bbox_pt"], [50, 400, 350, 625], atol=0.5)
    assert np.array_equal(np.asarray(Image.open(tmp_path / "out" / s["file"]).convert("RGB")), np.asarray(whole))


def test_tiles_in_a_grid_and_side_by_side(tmp_path):
    whole = picture(400, 400, 2)
    tiles = [(whole.crop((x, y, x + 200, y + 200)), x, y) for x in (0, 200) for y in (0, 200)]
    make_pdf(tmp_path / "b.pdf", [(t, 100 + x * 0.5, 700 - (y + 200) * 0.5, 100, 100) for t, x, y in tiles])
    man = extract_images.extract(tmp_path / "b.pdf", tmp_path / "out")
    got = stitch_images.stitch(man, tmp_path / "out")
    assert len(got) == 1 and got[0]["px"] == [400, 400]
    assert np.array_equal(np.asarray(Image.open(tmp_path / "out" / got[0]["file"]).convert("RGB")), np.asarray(whole))


def test_separate_pictures_are_left_alone(tmp_path):
    # a gap between them, and one at a different resolution touching the first
    make_pdf(tmp_path / "c.pdf", [(picture(200, 100, 3), 50, 500, 200, 100), (picture(200, 100, 4), 50, 380, 200, 100),
                                  (picture(50, 100, 5), 250, 500, 200, 100)])
    man = extract_images.extract(tmp_path / "c.pdf", tmp_path / "out")
    assert stitch_images.stitch(man, tmp_path / "out") == []
