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
