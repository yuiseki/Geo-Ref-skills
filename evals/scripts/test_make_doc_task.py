# uvx --with numpy --with pillow --with opencv-python-headless --with pypdfium2==5.14.0 --with pytest pytest scripts/test_make_doc_task.py
import json

import numpy as np
import pytest
from PIL import Image

import make_doc_task as mdt


def fake_task(tmp_path, W=300, H=200):
    t = tmp_path / "task"
    t.mkdir()
    rng = np.random.default_rng(0)
    Image.fromarray(rng.integers(0, 255, (H, W, 3), dtype=np.uint8)).save(t / "image.png")
    D = [[1.0, 0.0, 1000.0], [0.0, 1.0, 2000.0], [0.0, 0.0, 1.0]]
    truth = {"width": W, "height": H, "zoom": 15, "tile_size": 256, "task_px_to_global_px": D,
             "footprint_lonlat": [[0, 0], [1, 0], [1, 1], [0, 1]]}
    (tmp_path / "truth.json").write_text(json.dumps(truth))
    return t / "image.png", truth


def test_a_crop_of_the_page_gets_the_composed_truth(tmp_path):
    img, truth = fake_task(tmp_path)
    pl = mdt.make_documents(img, tmp_path / "doc", seed=1, dpi=150)
    assert (tmp_path / "doc" / "scan.pdf").exists() and (tmp_path / "doc" / "embedded.pdf").exists()
    left, top, w, h = pl["map_pt"]
    # a crop at 300 dpi whose corner is the map's corner: crop px (c, r) is task px (c, r) * W / (w * 300 / 72)
    R = 300
    box = [left * R / 72, top * R / 72, (left + w) * R / 72, (top + h) * R / 72]
    t2 = mdt.crop_truth(truth, pl, box, R)
    assert t2["width"] == round(box[2] - box[0]) and t2["height"] == round(box[3] - box[1])
    D2 = np.array(t2["task_px_to_global_px"])
    s = truth["width"] / (w * R / 72)
    assert D2 @ [0, 0, 1] == pytest.approx([1000, 2000, 1])
    assert D2 @ [10, 20, 1] == pytest.approx([1000 + 10 * s, 2000 + 20 * s, 1])


def test_the_scan_page_shows_the_map_where_the_placement_says(tmp_path):
    img, truth = fake_task(tmp_path)
    pl = mdt.make_documents(img, tmp_path / "doc", seed=2, dpi=150)
    page = np.asarray(Image.open(tmp_path / "doc" / "page.png").convert("RGB")).astype(int)
    left, top, w, h = pl["map_pt"]
    x0, y0 = int(round(left * 150 / 72)), int(round(top * 150 / 72))
    x1, y1 = int(round((left + w) * 150 / 72)), int(round((top + h) * 150 / 72))
    inside = page[y0 + 3:y1 - 3, x0 + 3:x1 - 3]
    assert inside.std() > 40  # the noisy map, not white paper
    assert page[5:40, 5:40].min() > 240  # the page margin is white


def test_the_tiled_document_stitches_back_into_the_map(tmp_path):
    import sys
    sys.path.insert(0, str(mdt.Path(__file__).resolve().parents[2] / ".agents/skills/document-maps/scripts"))
    import extract_images
    import stitch_images
    img, truth = fake_task(tmp_path)
    mdt.make_documents(img, tmp_path / "doc", seed=3, dpi=150)
    man = extract_images.extract(tmp_path / "doc" / "tiled.pdf", tmp_path / "ex")
    assert len(man["images"]) >= 4  # the background and three strips or more
    got = stitch_images.stitch(man, tmp_path / "ex")
    assert len(got) == 1
    back = np.asarray(Image.open(tmp_path / "ex" / got[0]["file"]).convert("RGB"))
    assert np.array_equal(back, np.asarray(Image.open(img).convert("RGB")))


def test_the_paper_scan_is_off_white_and_noisy_with_the_map_in_place(tmp_path):
    img, truth = fake_task(tmp_path)
    pl = mdt.make_documents(img, tmp_path / "doc", seed=4, dpi=150)
    import pypdfium2 as pdfium
    pg = pdfium.PdfDocument(str(tmp_path / "doc" / "paper.pdf"))[0]
    objs = list(pg.get_objects())
    assert len(objs) == 1
    page = np.asarray(objs[0].get_bitmap(render=False).to_pil().convert("RGB")).astype(int)
    margin = page[5:40, 5:40]
    assert 200 < margin.mean() < 245 and margin.std() > 1.5
    left, top, w, h = pl["map_pt"]
    x0, y0 = int(round(left * 150 / 72)), int(round(top * 150 / 72))
    x1, y1 = int(round((left + w) * 150 / 72)), int(round((top + h) * 150 / 72))
    assert page[y0 + 3:y1 - 3, x0 + 3:x1 - 3].std() > 40
