# uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with opencv-python-headless --with pytest pytest scripts/test_map_candidates.py
import json

import cv2
import numpy as np
import pytest
from PIL import Image

import map_candidates as mc
from test_extract_images import make_pdf
from test_find_map_rectangles import map_like

A4 = (595, 842)
MAP_PT = (100, 300, 450, 550)  # x0, y0, x1, y1 in PDF points, origin bottom left


def page_with_text(dpi=150):
    W, H = int(A4[0] * dpi / 72), int(A4[1] * dpi / 72)
    p = np.full((H, W, 3), 255, np.uint8)
    for i in range(10):
        y = 80 + i * 24
        for x in range(80, W - 80, 20):
            cv2.rectangle(p, (x, y), (x + 13, y + 10), (40, 40, 40), -1)
    return p


def pil(a):
    return Image.fromarray(cv2.cvtColor(a, cv2.COLOR_BGR2RGB))


def map_px(dpi=150):
    x0, y0, x1, y1 = MAP_PT
    k = dpi / 72
    return int(round(x0 * k)), int(round((A4[1] - y1) * k)), int(round(x1 * k)), int(round((A4[1] - y0) * k))


def test_an_embedded_map_comes_before_the_page_background(tmp_path):
    m = map_like(700, 500)
    x0, y0, x1, y1 = MAP_PT
    make_pdf(tmp_path / "a.pdf", [(pil(page_with_text()), 0, 0, *A4), (pil(m), x0, y0, x1 - x0, y1 - y0)])
    got = mc.collect(tmp_path / "a.pdf", tmp_path / "out")
    first = got["candidates"][0]
    assert first["from"]["kind"] == "image" and first["page"] == 1
    assert first["bbox_pt"] == pytest.approx(list(MAP_PT), abs=0.5)
    assert np.array_equal(cv2.imread(str(tmp_path / "out" / first["file"])), m)
    assert json.loads((tmp_path / "out" / "candidates.json").read_text()) == got


def test_a_map_on_a_scanned_page_is_cut_out(tmp_path):
    p = page_with_text()
    x0, y0, x1, y1 = map_px()
    p[y0:y1, x0:x1] = map_like(x1 - x0, y1 - y0)
    make_pdf(tmp_path / "b.pdf", [(pil(p), 0, 0, *A4)])
    got = mc.collect(tmp_path / "b.pdf", tmp_path / "out")
    first = got["candidates"][0]
    assert first["from"]["kind"] == "rectangle"
    assert first["bbox_pt"] == pytest.approx(list(MAP_PT), abs=3)
    assert got["candidates"][-1]["from"]["kind"] in ("image", "rendered")


def test_strips_are_joined_before_anything_else(tmp_path):
    m = map_like(700, 500)
    x0, y0, x1, y1 = MAP_PT
    strips = [(pil(m[r:r + 100]), x0, y1 - (r + 100) / 2, x1 - x0, 50) for r in range(0, 500, 100)]
    make_pdf(tmp_path / "c.pdf", [(pil(page_with_text()), 0, 0, *A4)] + strips)
    got = mc.collect(tmp_path / "c.pdf", tmp_path / "out")
    first = got["candidates"][0]
    assert first["from"]["kind"] == "stitched"
    assert np.array_equal(cv2.imread(str(tmp_path / "out" / first["file"])), m)


def test_a_vector_map_is_found_on_the_rendered_page(tmp_path):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(*A4)
    g = np.random.default_rng(0)
    x0, y0, x1, y1 = MAP_PT
    cells = 14
    for i in range(cells):
        for j in range(cells):
            obj = raw.FPDFPageObj_CreateNewRect(x0 + (x1 - x0) * i / cells, y0 + (y1 - y0) * j / cells,
                                                (x1 - x0) / cells, (y1 - y0) / cells)
            r, gg, b = (int(v) for v in g.choice([[200, 220, 240], [230, 230, 200], [210, 240, 210], [250, 200, 180]]))
            raw.FPDFPageObj_SetFillColor(obj, r, gg, b, 255)
            raw.FPDFPageObj_SetStrokeColor(obj, 255, 255, 255, 255)
            raw.FPDFPageObj_SetStrokeWidth(obj, ctypes_float(1.5))
            raw.FPDFPath_SetDrawMode(obj, raw.FPDF_FILLMODE_ALTERNATE, True)
            raw.FPDFPage_InsertObject(pg.raw, obj)
    pg.gen_content()
    doc.save(str(tmp_path / "d.pdf"))
    got = mc.collect(tmp_path / "d.pdf", tmp_path / "out", render_dpi=100)
    first = got["candidates"][0]
    assert first["from"]["kind"] == "rendered" and first["dpi"] == 100
    assert first["bbox_pt"] == pytest.approx(list(MAP_PT), abs=4)


def ctypes_float(v):
    import ctypes
    return ctypes.c_float(v)


def test_an_image_file_gives_its_rectangles_then_itself(tmp_path):
    p = page_with_text()
    x0, y0, x1, y1 = map_px()
    p[y0:y1, x0:x1] = map_like(x1 - x0, y1 - y0)
    cv2.imwrite(str(tmp_path / "poster.png"), p)
    got = mc.collect(tmp_path / "poster.png", tmp_path / "out")
    kinds = [c["from"]["kind"] for c in got["candidates"]]
    assert kinds[0] == "rectangle" and kinds[-1] == "image"
    b = got["candidates"][0]["from"]["box_px"]
    assert all(abs(u - v) <= 6 for u, v in zip(b, (x0, y0, x1, y1))), b
    assert "bbox_pt" not in got["candidates"][0]


def stroked_rect(pg, x, y, w, h):
    import pypdfium2.raw as raw
    obj = raw.FPDFPageObj_CreateNewRect(x, y, w, h)
    raw.FPDFPageObj_SetStrokeColor(obj, 0, 0, 0, 255)
    raw.FPDFPageObj_SetStrokeWidth(obj, ctypes_float(1.0))
    raw.FPDFPath_SetDrawMode(obj, 0, True)
    raw.FPDFPage_InsertObject(pg.raw, obj)


def test_frames_drawn_as_vector_rectangles_are_candidates_and_so_is_the_rest_beside_an_inset(tmp_path):
    # a deployment map (MONUSCO, 2024): the country on the left, an enlargement of its east in its own frame on the
    # right, spanning the map's height; the rendered page alone gave neither panel by itself
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(*A4)
    stroked_rect(pg, 50, 100, 495, 600)   # the map frame
    stroked_rect(pg, 350, 100, 195, 600)  # the inset, along its right side
    stroked_rect(pg, 60, 110, 20, 20)     # a legend box: too small
    pg.gen_content()
    doc.save(str(tmp_path / "f.pdf"))
    got_frames = sorted(mc.vector_frames(tmp_path / "f.pdf", 1))
    want = sorted([(50, 100, 545, 700), (350, 100, 545, 700), (50, 100, 350, 700)])
    assert len(got_frames) == 3 and all(list(g) == pytest.approx(list(w), abs=1) for g, w in zip(got_frames, want))
    got = mc.collect(tmp_path / "f.pdf", tmp_path / "out", render_dpi=72)
    boxes = [c["bbox_pt"] for c in got["candidates"] if c["from"].get("frame")]
    for want in ([350, 100, 545, 700], [50, 100, 350, 700]):
        assert any(b == pytest.approx(want, abs=2) for b in boxes)


def test_frames_of_a_turned_page_are_where_the_page_shows_them(tmp_path):
    # portrait pages turned by /Rotate 90 (UN maps of 2021 and 2022): paths are in the unturned page's space
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(612, 792)
    stroked_rect(pg, 100, 200, 300, 400)  # unturned: x 100..400, y 200..600 (bottom-left origin)
    pg.gen_content()
    pg.set_rotation(90)
    doc.save(str(tmp_path / "t.pdf"))
    # shown 792 wide, 612 high; a quarter turn clockwise puts unturned (x, y) at (y, 612 - x), bottom-left origin
    (b,) = mc.vector_frames(tmp_path / "t.pdf", 1)
    assert list(b) == pytest.approx([200, 212, 600, 512], abs=1)


def test_frames_of_a_cropped_page_are_where_the_page_shows_them(tmp_path):
    # WFP's access constraints maps (2025-2026): a landscape sheet on a portrait page, cut out by a CropBox
    # (0, 229, 612, 562); the frame came out 229 pt too high and the map's lower half was cut off (2026-11-05)
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(612, 792)
    stroked_rect(pg, 100, 300, 300, 200)  # x 100..400, y 300..500 (bottom-left origin)
    pg.gen_content()
    pg.set_cropbox(30, 229, 612, 562)
    doc.save(str(tmp_path / "c.pdf"))
    (b,) = mc.vector_frames(tmp_path / "c.pdf", 1)
    assert list(b) == pytest.approx([70, 71, 370, 271], abs=1)
