# uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with pytest pytest scripts/test_extract_images.py
import hashlib
import json
import zipfile

import pytest
from PIL import Image

import extract_images


def pil(w, h, colour):
    return Image.new("RGB", (w, h), colour)


def make_pdf(path, placements, page=(595, 842)):
    """placements: [(PIL image, x_pt, y_pt, w_pt, h_pt)] on one page (PDF points, origin bottom left)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(*page)
    for im, x, y, w, h in placements:
        obj = pdfium.PdfImage.new(doc)
        obj.set_bitmap(pdfium.PdfBitmap.from_pil(im))
        obj.set_matrix(pdfium.PdfMatrix().scale(w, h).translate(x, y))
        pg.insert_obj(obj)
    pg.gen_content()
    doc.save(str(path))


def test_pdf_images_come_out_with_page_and_place(tmp_path):
    src = tmp_path / "a.pdf"
    make_pdf(src, [(pil(400, 300, (200, 220, 240)), 50, 400, 300, 225), (pil(64, 64, (10, 10, 10)), 400, 50, 32, 32)])
    out = tmp_path / "out"
    man = extract_images.extract(src, out)
    assert man["source"]["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert man["tool"]["pypdfium2"] and man["tool"]["pdfium"]
    imgs = sorted(man["images"], key=lambda i: -i["px"][0])
    assert [i["px"] for i in imgs] == [[400, 300], [64, 64]]
    big = imgs[0]
    assert big["page"] == 1 and big["page_size_pt"] == [595, 842]
    assert big["bbox_pt"] == pytest.approx([50, 400, 350, 625], abs=0.5)
    assert Image.open(out / big["file"]).size == (400, 300)
    assert json.loads((out / "manifest.json").read_text()) == man


def test_office_media_come_out_with_their_part(tmp_path):
    src = tmp_path / "b.pptx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/slides/slide1.xml", "<p:sld/>")
        for name, im in (("ppt/media/image1.png", pil(120, 80, (0, 128, 0))), ("ppt/media/image2.jpeg", pil(50, 40, (9, 9, 9)))):
            import io
            b = io.BytesIO()
            im.save(b, format="PNG" if name.endswith("png") else "JPEG")
            z.writestr(name, b.getvalue())
        z.writestr("ppt/media/notes.txt", "not an image")
    out = tmp_path / "out"
    man = extract_images.extract(src, out)
    got = sorted((i["part"], tuple(i["px"])) for i in man["images"])
    assert got == [("ppt/media/image1.png", (120, 80)), ("ppt/media/image2.jpeg", (50, 40))]
    assert all((out / i["file"]).exists() for i in man["images"])


def test_unknown_format_is_an_error(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("hello")
    with pytest.raises(ValueError):
        extract_images.extract(p, tmp_path / "out")


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("origin", [(0, 0), (100, -50)])
def test_bbox_is_where_the_image_shows_on_the_drawn_page(tmp_path, rotation, origin):
    # bbox_pt is on the page as it is shown (rotation and the media box applied), the frame render_pages draws:
    # Commons PDFs with /Rotate 90 put the map's box off the drawn page
    import numpy as np
    import pypdfium2 as pdfium
    l, b = origin
    doc = pdfium.PdfDocument.new()
    pg = doc.new_page(400, 300)
    pg.set_mediabox(l, b, l + 400, b + 300)
    obj = pdfium.PdfImage.new(doc)
    obj.set_bitmap(pdfium.PdfBitmap.from_pil(pil(40, 20, (255, 0, 0))))
    obj.set_matrix(pdfium.PdfMatrix().scale(80, 40).translate(l + 30, b + 200))
    pg.insert_obj(obj)
    pg.gen_content()
    pg.set_rotation(rotation)
    src = tmp_path / "r.pdf"
    doc.save(str(src))
    man = extract_images.extract(src, tmp_path / "out")
    im = man["images"][0]
    page = pdfium.PdfDocument(str(src))[0]
    a = np.asarray(page.render(scale=1).to_pil().convert("RGB")).astype(int)
    H, W = a.shape[:2]
    assert im["page_size_pt"] == pytest.approx([W, H], abs=1)
    red = (a[..., 0] > 200) & (a[..., 1] < 60)
    ys, xs = np.nonzero(red)
    shown = [xs.min(), H - ys.max() - 1, xs.max() + 1, H - ys.min()]
    assert im["bbox_pt"] == pytest.approx(shown, abs=1.5)
