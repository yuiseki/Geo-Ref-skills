# uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with pytest pytest scripts/test_render_pages.py
import numpy as np
import pytest
from PIL import Image

import render_pages
from test_extract_images import make_pdf, pil


def test_pages_are_drawn_at_the_asked_dpi_with_pdf_points_mapped_to_pixels(tmp_path):
    src = tmp_path / "a.pdf"
    make_pdf(src, [(pil(10, 10, (0, 0, 0)), 100, 600, 50, 40)], page=(400, 800))
    man = render_pages.render(src, tmp_path / "out", dpi=144)
    p = man["pages"][0]
    assert p["dpi"] == 144 and p["px"] == [800, 1600] and p["page_size_pt"] == [400, 800]
    a = np.asarray(Image.open(tmp_path / "out" / p["file"]).convert("L"))
    assert a.shape == (1600, 800)
    # the black box spans x 100..150 pt and y 600..640 pt (from the bottom): pixels x 200..300, rows 320..400
    ys, xs = np.nonzero(a < 50)
    assert (xs.min(), xs.max()) == pytest.approx((200, 299), abs=2)
    assert (ys.min(), ys.max()) == pytest.approx((320, 399), abs=2)
    assert render_pages.pt_to_px(100, 600, p) == pytest.approx((200, 400))
    assert man["source"]["sha256"] and man["tool"]["pdfium"]


def test_only_the_asked_pages(tmp_path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(3):
        doc.new_page(100, 100)
    src = tmp_path / "three.pdf"
    doc.save(str(src))
    man = render_pages.render(src, tmp_path / "out", dpi=72, pages=[2])
    assert [p["page"] for p in man["pages"]] == [2]
