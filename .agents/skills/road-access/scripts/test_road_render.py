# uvx --with numpy --with opencv-python-headless --with pillow --with pytest pytest scripts/test_road_render.py
import numpy as np

import road_render as rr
import transforms as tf


def test_the_map_is_warped_to_the_reference_through_the_inverse_of_the_answer():
    # panel pixel (c, r) -> mercator (1000 c, -1000 r); the reference: 1 px = 2000 m from (0, 0)
    src = np.array([[0, 0], [100, 0], [0, 100], [100, 100]], float)
    dst = np.array([[c * 1000, -r * 1000] for c, r in src])
    panel = np.zeros((100, 100, 3), np.uint8)
    panel[40:60, 20:30] = (0, 0, 255)  # a red block at c 20..30, r 40..60
    gt = [0.0, 2000.0, 0.0, 0.0, 0.0, -2000.0]
    out, alpha = rr.warp(panel, "affine", src, dst, gt, (60, 60), masks=[])
    assert tuple(out[25, 12]) == (0, 0, 255)  # c 24, r 50 -> mercator (24000, -50000) -> ref (12, 25)
    assert alpha[25, 12] == 1 and alpha[55, 55] == 0  # beyond the panel


def test_masked_boxes_are_left_out_of_the_warp():
    src = np.array([[0, 0], [100, 0], [0, 100], [100, 100]], float)
    dst = np.array([[c * 1000, -r * 1000] for c, r in src])
    panel = np.full((100, 100, 3), 200, np.uint8)
    gt = [0.0, 1000.0, 0.0, 0.0, 0.0, -1000.0]
    out, alpha = rr.warp(panel, "affine", src, dst, gt, (100, 100), masks=[[50, 0, 100, 100]])
    assert alpha[10, 20] == 1 and alpha[10, 70] == 0


def test_frames_are_in_date_order_with_lengths_by_status():
    docs = [{"map_date": "2026-02-01", "features": [
                {"geometry": {"type": "LineString", "coordinates": [[30, 7], [30, 8]]}, "properties": {"status": "passable"}}]},
            {"map_date": "2026-01-01", "features": [
                {"geometry": {"type": "MultiLineString", "coordinates": [[[30, 7], [31, 7]], [[30, 6], [30, 6.5]]]},
                 "properties": {"status": "not passable"}}]}]
    fr = rr.frames_of(docs)
    assert [d for d, _, _ in fr] == ["2026-01-01", "2026-02-01"]
    km = fr[1][2]
    assert abs(km["passable"] - 111.2) < 1 and fr[0][2]["not passable"] > 150


def test_a_palette_keeps_the_status_colours_exactly():
    from PIL import Image, ImageDraw
    base = Image.new("RGB", (50, 50), (240, 240, 240))
    ImageDraw.Draw(base).rectangle([0, 0, 25, 25], fill=(200, 220, 200))
    pal = rr.palette_for(base)
    img = base.copy()
    ImageDraw.Draw(img).line([(0, 40), (49, 40)], fill=rr.COLOURS["not passable"], width=3)
    q = img.quantize(palette=pal, dither=Image.NONE).convert("RGB")
    assert q.getpixel((20, 40)) == rr.COLOURS["not passable"]
